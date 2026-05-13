import asyncio
import json
import math
import os
from datetime import datetime, timezone, timedelta

import asyncpg
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse


OKX_BASE = os.environ.get("CRYPTO_OKX_BASE", "https://www.okx.com").rstrip("/")
TW_TZ = timezone(timedelta(hours=8))


def _symbols():
    raw = os.environ.get("CRYPTO_SYMBOLS", os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT"))
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


CONFIG = {
    "symbols": _symbols(),
    "dataSource": "OKX",
    "interval": os.environ.get("CRYPTO_INTERVAL", "5m"),
    "higherInterval": os.environ.get("CRYPTO_HIGHER_INTERVAL", "15m"),
    "pollSeconds": int(os.environ.get("CRYPTO_POLL_SECONDS", "300")),
    "startingCash": float(os.environ.get("CRYPTO_STARTING_CASH", "1000")),
    "orderQuoteSize": float(os.environ.get("CRYPTO_ORDER_QUOTE_SIZE", "50")),
    "takeProfitPct": float(os.environ.get("CRYPTO_TAKE_PROFIT_PCT", "1.2")),
    "stopLossPct": float(os.environ.get("CRYPTO_STOP_LOSS_PCT", "0.6")),
    "maxEntriesPerDay": int(os.environ.get("CRYPTO_MAX_ENTRIES_PER_DAY", "2")),
    "cooldownMinutes": int(os.environ.get("CRYPTO_COOLDOWN_MINUTES", "120")),
}

STRATEGIES = [
    {"id": "mtf_trend_pullback", "name": "15m Trend Pullback", "description": "15m uptrend filter, 5m pullback recovery entry."},
    {"id": "mtf_macd_momentum", "name": "15m MACD Momentum", "description": "15m MACD positive, 5m momentum turns up."},
    {"id": "vwap_reclaim", "name": "VWAP Reclaim", "description": "15m structure neutral/up, 5m price reclaims VWAP."},
    {"id": "range_breakout_15m", "name": "15m Range Breakout", "description": "15m compression, 5m breakout with volume."},
    {"id": "rsi_exhaustion_bounce", "name": "15m RSI Bounce", "description": "15m not bearish, 5m exhaustion bounce setup."},
]

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS crypto_state (
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(symbol, strategy)
);
CREATE TABLE IF NOT EXISTS crypto_signals (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT,
    strategy TEXT,
    price DOUBLE PRECISION,
    signal TEXT,
    reason TEXT,
    action TEXT,
    equity DOUBLE PRECISION,
    return_pct DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS crypto_trades (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT,
    strategy TEXT,
    side TEXT,
    price DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    quote_amount DOUBLE PRECISION,
    reason TEXT
);
"""


class CryptoPaperBot:
    def __init__(self):
        self.pool = None
        self.running = False
        self.task = None
        self.last_error = ""
        self.last_run_at = None
        self.snapshots = {}

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None

    async def setup(self):
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        if not database_url.startswith("postgresql://"):
            raise RuntimeError("CRYPTO bot needs Render PostgreSQL DATABASE_URL.")
        self.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
        async with self.pool.acquire() as conn:
            await conn.execute(CREATE_SQL)

    async def close(self):
        await self.stop()
        if self.pool:
            await self.pool.close()

    async def _loop(self):
        while self.running:
            try:
                await self.run_once()
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
            await asyncio.sleep(CONFIG["pollSeconds"])

    async def run_once(self):
        async with httpx.AsyncClient(timeout=20) as client:
            for symbol in CONFIG["symbols"]:
                candles, higher = await asyncio.gather(
                    fetch_klines(client, symbol, CONFIG["interval"], 180),
                    fetch_klines(client, symbol, CONFIG["higherInterval"], 180),
                )
                await self._apply_symbol(symbol, candles, higher)
        self.last_run_at = datetime.now(timezone.utc).isoformat()

    async def _apply_symbol(self, symbol, candles, higher):
        price = candles[-1]["close"]
        close_time = candles[-1]["closeTime"]
        states = await self._load_states(symbol)
        rows = []
        for strategy in STRATEGIES:
            account = states[strategy["id"]]
            if account.get("lastCandleCloseTime") == close_time:
                rows.append(snapshot_row(strategy, account, price))
                continue
            refresh_daily_limit(account, close_time)
            decision = decide(strategy["id"], candles, higher, account)
            decision = with_risk_exit(decision, account, price)
            action = "no_trade"
            if decision["signal"] == "BUY" and account["assetQty"] <= 0:
                if can_enter(account, close_time):
                    quote = min(account["cash"], CONFIG["orderQuoteSize"])
                    qty = quote / price
                    account["cash"] -= quote
                    account["assetQty"] += qty
                    account["avgEntry"] = price
                    account["entryCountToday"] += 1
                    account["trades"] += 1
                    action = "buy_paper"
                    await self._log_trade(symbol, strategy["id"], "BUY", price, qty, quote, decision["reason"])
                else:
                    action = "skip_daily_limit_or_cooldown"
            elif decision["signal"] == "SELL" and account["assetQty"] > 0:
                qty = account["assetQty"]
                quote = qty * price
                pnl = quote - qty * account["avgEntry"]
                account["cash"] += quote
                account["assetQty"] = 0
                account["avgEntry"] = 0
                account["lastExitTime"] = close_time
                account["realizedPnl"] += pnl
                account["trades"] += 1
                account["closedTrades"] += 1
                account["wins"] += 1 if pnl > 0 else 0
                action = "sell_paper"
                await self._log_trade(symbol, strategy["id"], "SELL", price, qty, quote, decision["reason"])

            equity = account["cash"] + account["assetQty"] * price
            account["peakEquity"] = max(account["peakEquity"], equity)
            if account["peakEquity"] > 0:
                account["maxDrawdownPct"] = max(account["maxDrawdownPct"], ((account["peakEquity"] - equity) / account["peakEquity"]) * 100)
            account["lastSignal"] = decision["signal"]
            account["lastReason"] = decision["reason"]
            account["lastAction"] = action
            account["lastCandleCloseTime"] = close_time
            await self._save_state(symbol, strategy["id"], account)
            await self._log_signal(symbol, strategy["id"], price, decision, action, equity)
            rows.append(snapshot_row(strategy, account, price))

        rows.sort(key=lambda row: row["equity"], reverse=True)
        self.snapshots[symbol] = {
            "config": {**CONFIG, "symbol": symbol},
            "running": self.running,
            "lastError": self.last_error,
            "lastRunAt": self.last_run_at,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "lastPrice": price,
            "strategies": rows,
            "candles": candles[-80:],
        }

    async def _load_states(self, symbol):
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT strategy, state FROM crypto_state WHERE symbol=$1", symbol)
        states = {}
        for record in records:
            raw_state = record["state"]
            states[record["strategy"]] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
        for strategy in STRATEGIES:
            states.setdefault(strategy["id"], new_account())
        return states

    async def _save_state(self, symbol, strategy, state):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_state(symbol,strategy,state,updated_at)
                   VALUES($1,$2,$3::jsonb,NOW())
                   ON CONFLICT(symbol,strategy) DO UPDATE SET state=$3::jsonb, updated_at=NOW()""",
                symbol,
                strategy,
                json.dumps(state),
            )

    async def _log_signal(self, symbol, strategy, price, decision, action, equity):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_signals(symbol,strategy,price,signal,reason,action,equity,return_pct)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                symbol, strategy, price, decision["signal"], decision["reason"], action,
                equity, ((equity - CONFIG["startingCash"]) / CONFIG["startingCash"]) * 100,
            )

    async def _log_trade(self, symbol, strategy, side, price, qty, quote, reason):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_trades(symbol,strategy,side,price,quantity,quote_amount,reason)
                   VALUES($1,$2,$3,$4,$5,$6,$7)""",
                symbol, strategy, side, price, qty, quote, reason,
            )

    def status(self):
        markets = []
        for symbol in CONFIG["symbols"]:
            markets.append(self.snapshots.get(symbol) or empty_snapshot(symbol, self.running, self.last_error, self.last_run_at))
        return {"running": self.running, "markets": markets, "config": CONFIG, "lastError": self.last_error, "lastRunAt": self.last_run_at}


crypto_bot = CryptoPaperBot()


def install_crypto_bot(app: FastAPI):
    @app.on_event("startup")
    async def crypto_startup():
        await crypto_bot.setup()
        await crypto_bot.start()

    @app.on_event("shutdown")
    async def crypto_shutdown():
        await crypto_bot.close()

    @app.get("/crypto", response_class=HTMLResponse)
    async def crypto_dashboard():
        return HTMLResponse(CRYPTO_HTML)

    @app.get("/api/crypto/status")
    async def crypto_status():
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/start")
    async def crypto_start():
        await crypto_bot.start()
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/stop")
    async def crypto_stop():
        await crypto_bot.stop()
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/run-once")
    async def crypto_run_once():
        await crypto_bot.run_once()
        return JSONResponse(crypto_bot.status())

    @app.get("/api/crypto/trades")
    async def crypto_trades(symbol: str = Query("", max_length=20)):
        sql = "SELECT ts,symbol,strategy,side,price,quantity,quote_amount,reason FROM crypto_trades"
        args = []
        if symbol:
            sql += " WHERE symbol=$1"
            args.append(symbol.upper())
        sql += " ORDER BY ts DESC LIMIT 100"
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)


async def fetch_klines(client, symbol, interval, limit):
    inst_id = to_okx_inst_id(symbol)
    params = {"instId": inst_id, "bar": interval, "limit": str(limit)}
    resp = await client.get(f"{OKX_BASE}/api/v5/market/candles", params=params)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX candles error: {payload}")
    return [
        {
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
            "closeTime": int(r[0]),
        }
        for r in reversed(payload["data"])
    ]


def to_okx_inst_id(symbol):
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT"
    if symbol.endswith("USDC"):
        return f"{symbol[:-4]}-USDC"
    return symbol


def new_account():
    return {
        "cash": CONFIG["startingCash"], "assetQty": 0.0, "avgEntry": 0.0,
        "peakEquity": CONFIG["startingCash"], "maxDrawdownPct": 0.0,
        "realizedPnl": 0.0, "trades": 0, "closedTrades": 0, "wins": 0,
        "lastSignal": "HOLD", "lastReason": "not_started", "lastAction": "none",
        "entryDay": None, "entryCountToday": 0, "lastExitTime": 0, "lastCandleCloseTime": 0,
    }


def refresh_daily_limit(account, timestamp_ms):
    day = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()
    if account.get("entryDay") != day:
        account["entryDay"] = day
        account["entryCountToday"] = 0


def can_enter(account, timestamp_ms):
    refresh_daily_limit(account, timestamp_ms)
    cooldown_ms = CONFIG["cooldownMinutes"] * 60 * 1000
    return account["entryCountToday"] < CONFIG["maxEntriesPerDay"] and (not account["lastExitTime"] or timestamp_ms - account["lastExitTime"] >= cooldown_ms)


def snapshot_row(strategy, account, price):
    equity = account["cash"] + account["assetQty"] * price
    position_value = account["assetQty"] * price
    entry_cost = account["assetQty"] * account["avgEntry"]
    unreal = position_value - entry_cost if account["assetQty"] > 0 else 0.0
    return {
        "id": strategy["id"], "name": strategy["name"], "description": strategy["description"],
        "cash": rnd(account["cash"]), "assetQty": rnd(account["assetQty"], 8),
        "avgEntry": rnd(account["avgEntry"]), "positionValue": rnd(position_value),
        "unrealizedPnl": rnd(unreal), "unrealizedPnlPct": rnd((unreal / entry_cost) * 100 if entry_cost else 0),
        "equity": rnd(equity), "returnPct": rnd(((equity - CONFIG["startingCash"]) / CONFIG["startingCash"]) * 100),
        "realizedPnl": rnd(account["realizedPnl"]), "maxDrawdownPct": rnd(account["maxDrawdownPct"]),
        "trades": account["trades"], "wins": account["wins"], "entriesToday": account["entryCountToday"],
        "winRate": rnd((account["wins"] / account["closedTrades"]) * 100 if account["closedTrades"] else 0),
        "inPosition": account["assetQty"] > 0, "lastSignal": account["lastSignal"],
        "lastReason": account["lastReason"], "lastAction": account["lastAction"],
    }


def empty_snapshot(symbol, running, error, last_run_at):
    return {"config": {**CONFIG, "symbol": symbol}, "running": running, "lastError": error, "lastRunAt": last_run_at, "updatedAt": None, "lastPrice": 0, "strategies": [snapshot_row(s, new_account(), 0) for s in STRATEGIES], "candles": []}


def with_risk_exit(decision, account, price):
    if account["assetQty"] <= 0:
        return decision
    if price <= account["avgEntry"] * (1 - CONFIG["stopLossPct"] / 100):
        return {"signal": "SELL", "reason": "stop_loss"}
    if price >= account["avgEntry"] * (1 + CONFIG["takeProfitPct"] / 100):
        return {"signal": "SELL", "reason": "take_profit"}
    return decision


def decide(strategy_id, candles, higher, account):
    closes = [c["close"] for c in candles]
    closes15 = [c["close"] for c in higher]
    in_pos = account["assetQty"] > 0
    if strategy_id == "mtf_trend_pullback":
        fast, slow, r, avg = sma(closes15, 8), sma(closes15, 21), rsi(closes, 14), sma(closes, 20)
        if None in (fast, slow, r, avg): return hold("warming_up")
        if not in_pos and fast > slow and closes[-1] > avg and 45 < r < 62: return buy("15m_uptrend_5m_recovery")
        if in_pos and (fast < slow or r > 72): return sell("trend_faded_or_overheated")
    elif strategy_id == "mtf_macd_momentum":
        m15, m5 = macd(closes15), macd(closes)
        avg_vol = sma([c["volume"] for c in candles[-21:-1]], 20)
        if not m15 or not m5 or avg_vol is None: return hold("warming_up")
        if not in_pos and m15["histogram"] > 0 and m5["previousHistogram"] <= 0 and m5["histogram"] > 0 and candles[-1]["volume"] > avg_vol: return buy("15m_macd_5m_turn")
        if in_pos and m5["histogram"] < 0: return sell("5m_momentum_lost")
    elif strategy_id == "vwap_reclaim":
        fast, slow, vw, pvw = sma(closes15, 8), sma(closes15, 21), vwap(candles, 48), vwap(candles[:-1], 48)
        if None in (fast, slow, vw, pvw) or len(candles) < 2: return hold("warming_up")
        if not in_pos and fast >= slow * 0.998 and candles[-2]["close"] < pvw and candles[-1]["close"] > vw: return buy("vwap_reclaim")
        if in_pos and candles[-1]["close"] < vw: return sell("lost_vwap")
    elif strategy_id == "range_breakout_15m":
        mid, dev, a = sma(closes15, 20), stddev(closes15, 20), atr(higher, 14)
        if None in (mid, dev, a) or len(candles) < 35: return hold("warming_up")
        prev = candles[-25:-1]
        high = max(c["high"] for c in prev)
        avg_vol = sum(c["volume"] for c in prev) / len(prev)
        if not in_pos and (dev / mid < 0.004 or a / mid < 0.004) and candles[-1]["close"] > high and candles[-1]["volume"] > avg_vol * 1.25: return buy("compressed_range_breakout")
        avg20 = sma(closes, 20)
        if in_pos and avg20 and candles[-1]["close"] < avg20: return sell("breakout_failed")
    elif strategy_id == "rsi_exhaustion_bounce":
        r5, r15, avg = rsi(closes, 14), rsi(closes15, 14), sma(closes, 12)
        if None in (r5, r15, avg) or len(candles) < 2: return hold("warming_up")
        green = candles[-2]["close"] < candles[-2]["open"] and candles[-1]["close"] > candles[-1]["open"] and candles[-1]["close"] > avg
        if not in_pos and r15 > 38 and r5 < 34 and green: return buy("exhaustion_bounce")
        if in_pos and (r5 > 58 or candles[-1]["close"] < avg): return sell("bounce_completed")
    return hold("no_signal")


def buy(reason): return {"signal": "BUY", "reason": reason}
def sell(reason): return {"signal": "SELL", "reason": reason}
def hold(reason): return {"signal": "HOLD", "reason": reason}
def rnd(value, digits=4): return round(value, digits) if math.isfinite(value) else 0


def sma(values, period):
    return None if len(values) < period else sum(values[-period:]) / period


def stddev(values, period):
    avg = sma(values, period)
    if avg is None: return None
    return math.sqrt(sum((v - avg) ** 2 for v in values[-period:]) / period)


def rsi(values, period):
    if len(values) <= period: return None
    gains = losses = 0.0
    recent = values[-period - 1:]
    for prev, cur in zip(recent[:-1], recent[1:]):
        diff = cur - prev
        gains += max(diff, 0)
        losses += abs(min(diff, 0))
    if losses == 0: return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def ema_series(values, period):
    if len(values) < period: return []
    mult = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out = [prev]
    for value in values[period:]:
        prev = (value - prev) * mult + prev
        out.append(prev)
    return out


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal: return None
    fast_s, slow_s = ema_series(values, fast), ema_series(values, slow)
    offset = len(fast_s) - len(slow_s)
    line = [fast_s[i + offset] - slow_s[i] for i in range(len(slow_s))]
    sig = ema_series(line, signal)
    if len(sig) < 2: return None
    return {"histogram": line[-1] - sig[-1], "previousHistogram": line[-2] - sig[-2]}


def atr(candles, period):
    if len(candles) <= period: return None
    ranges = []
    for prev, cur in zip(candles[-period - 1:-1], candles[-period:]):
        ranges.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]), abs(cur["low"] - prev["close"])))
    return sum(ranges) / period


def vwap(candles, period):
    if len(candles) < period: return None
    recent = candles[-period:]
    vol = sum(c["volume"] for c in recent)
    if vol == 0: return None
    return sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in recent) / vol


CRYPTO_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Crypto Strategy Lab</title>
<style>body{margin:0;background:#f5f7f4;color:#18201f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0}.controls{display:flex;gap:8px}button{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:700;cursor:pointer}main{max-width:1280px;margin:auto;padding:24px}.tabs{display:flex;gap:10px;margin-bottom:16px}.tabs button{min-width:120px}.active{border-color:#2867b2;box-shadow:inset 0 0 0 1px #2867b2}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel,.card{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px}canvas{width:100%;height:280px;border:1px solid #dce3df;border-radius:8px;background:#fbfcfb}.cards{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:12px}.card{padding:14px}.card.pos{border-color:rgba(22,131,95,.55);background:#fbfffc}.position{border:1px solid #dce3df;border-radius:8px;padding:10px;margin:10px 0;background:#f8faf8}.position.on{background:#effaf4}.stat{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #dce3df;padding-top:8px;margin-top:8px;font-size:13px}.good{color:#16835f}.bad{color:#c53b3b}@media(max-width:900px){.grid,.cards{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid,.cards{grid-template-columns:1fr}.top{align-items:flex-start}}</style></head>
<body><header class="top"><div><h1>Crypto Strategy Lab</h1><p id="sub">Loading...</p></div><div class="controls"><button id="run">Run</button><button id="toggle">Start</button></div></header><main><nav id="tabs" class="tabs"></nav><section class="grid"><div class="metric"><span>Last Price</span><strong id="price">--</strong></div><div class="metric"><span>Leader</span><strong id="leader">--</strong></div><div class="metric"><span>Best Return</span><strong id="ret">--</strong></div><div class="metric"><span>Mode</span><strong>Paper</strong></div></section><section class="panel"><h2>5m Candles</h2><p id="last">Waiting</p><canvas id="chart"></canvas></section><section><h2>Strategy Ranking</h2><div id="cards" class="cards"></div></section></main>
<script>
let state={data:null,symbol:""}; const $=s=>document.querySelector(s);
$("#run").onclick=()=>post("/api/crypto/run-once"); $("#toggle").onclick=()=>post(state.data?.running?"/api/crypto/stop":"/api/crypto/start");
setInterval(load,10000); load();
async function load(){state.data=await (await fetch("/api/crypto/status")).json(); render();}
async function post(url){state.data=await (await fetch(url,{method:"POST"})).json(); render();}
function markets(){return state.data?.markets||[]} function market(){let ms=markets(); if(!state.symbol&&ms[0])state.symbol=ms[0].config.symbol; return ms.find(m=>m.config.symbol===state.symbol)||ms[0];}
function render(){let m=market(); if(!m)return; let leader=m.strategies[0]; $("#sub").textContent=`${m.config.symbol} · 5m trigger / 15m structure`; $("#price").textContent=money(m.lastPrice); $("#leader").textContent=leader?.name||"--"; $("#ret").textContent=pct(leader?.returnPct||0); $("#ret").className=tone(leader?.returnPct||0); $("#toggle").textContent=state.data.running?"Stop":"Start"; $("#last").textContent=m.updatedAt?`Last update: ${new Date(m.updatedAt).toLocaleString()}`:"Waiting for first update"; tabs(); cards(m.strategies,m.lastPrice); chart(m.candles||[]);}
function tabs(){ $("#tabs").innerHTML=markets().map(m=>`<button class="${m.config.symbol===state.symbol?'active':''}" data-s="${m.config.symbol}">${m.config.symbol.replace('USDT','')}</button>`).join(""); document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{state.symbol=b.dataset.s;render();});}
function cards(strats, price){$("#cards").innerHTML=strats.map((s,i)=>{let pv=s.positionValue??s.assetQty*price; let cost=s.assetQty*s.avgEntry; let pnl=cost?((pv-cost)/cost*100):0; return `<article class="card ${s.inPosition?'pos':''}"><h3>${s.name}</h3><span class="label">${s.id}</span><p>${s.description}</p><div class="position ${s.inPosition?'on':''}"><span class="label">Position</span><strong>${s.inPosition?'Long '+money(pv):'Flat'}</strong>${s.inPosition?`<div>Qty ${qty(s.assetQty)}</div><div>Entry ${money(s.avgEntry)}</div><div class="${tone(pnl)}">P/L ${pct(pnl)}</div>`:''}</div>${stat('Equity',money(s.equity))}${stat('Return',`<span class="${tone(s.returnPct)}">${pct(s.returnPct)}</span>`)}${stat('Trades',s.trades)}${stat('Signal',s.lastSignal)}${stat('Reason',s.lastReason)}</article>`}).join("");}
function stat(k,v){return `<div class="stat"><span>${k}</span><strong>${v}</strong></div>`} function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2})} function qty(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:8})} function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`} function tone(v){return Number(v)>=0?'good':'bad'}
function chart(c){const canvas=$("#chart"),r=devicePixelRatio||1,rect=canvas.getBoundingClientRect();canvas.width=Math.max(640,rect.width*r);canvas.height=280*r;const x=canvas.getContext('2d');x.scale(r,r);x.clearRect(0,0,rect.width,280);if(!c.length){x.fillText('Waiting for candles',18,32);return}let hi=Math.max(...c.map(k=>k.high)),lo=Math.min(...c.map(k=>k.low)),span=Math.max(1,hi-lo),w=(rect.width-64)/c.length;function y(v){return 18+((hi-v)/span)*(238)};c.forEach((k,i)=>{let cx=16+i*w+w/2,up=k.close>=k.open;x.strokeStyle=x.fillStyle=up?'#16835f':'#c53b3b';x.beginPath();x.moveTo(cx,y(k.high));x.lineTo(cx,y(k.low));x.stroke();x.fillRect(cx-w*.25,Math.min(y(k.open),y(k.close)),Math.max(2,w*.5),Math.max(2,Math.abs(y(k.close)-y(k.open))))});}
</script></body></html>"""
