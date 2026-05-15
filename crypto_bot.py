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
    "microPollSeconds": int(os.environ.get("CRYPTO_MICRO_POLL_SECONDS", "300")),
    "microOrderQuoteSize": float(os.environ.get("CRYPTO_MICRO_ORDER_QUOTE_SIZE", "50")),
    "microMaxPositions": int(os.environ.get("CRYPTO_MICRO_MAX_POSITIONS", "8")),
    "microMinQuoteVolume24h": float(os.environ.get("CRYPTO_MICRO_MIN_QUOTE_VOLUME_24H", "500000")),
    "microMaxQuoteVolume24h": float(os.environ.get("CRYPTO_MICRO_MAX_QUOTE_VOLUME_24H", "80000000")),
    "microMinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_MIN_VOLUME_RATIO", "3")),
    "microMinBreakoutPct5m": float(os.environ.get("CRYPTO_MICRO_MIN_BREAKOUT_PCT_5M", "2")),
    "microMinBreakoutPct15m": float(os.environ.get("CRYPTO_MICRO_MIN_BREAKOUT_PCT_15M", "3")),
    "microInstType": os.environ.get("CRYPTO_MICRO_INST_TYPE", "SWAP").upper(),
    "microTrendVolumeRatio": float(os.environ.get("CRYPTO_MICRO_TREND_VOLUME_RATIO", "1.35")),
    "microTrendMinPct1h": float(os.environ.get("CRYPTO_MICRO_TREND_MIN_PCT_1H", "1.2")),
    "microTrendMinPct15m": float(os.environ.get("CRYPTO_MICRO_TREND_MIN_PCT_15M", "0.4")),
    "microStopLossPct": float(os.environ.get("CRYPTO_MICRO_STOP_LOSS_PCT", "1.0")),
}

MICRO_EXCLUDED_BASES = {"BTC", "ETH", "BNB", "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USD", "EUR", "BRL"}

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
CREATE TABLE IF NOT EXISTS crypto_candles (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    source TEXT,
    PRIMARY KEY(symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS crypto_micro_state (
    inst_id TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crypto_micro_trades (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    inst_id TEXT,
    side TEXT,
    price DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    quote_amount DOUBLE PRECISION,
    ma60 DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    pct5 DOUBLE PRECISION,
    pct15 DOUBLE PRECISION,
    reason TEXT
);
"""


class CryptoPaperBot:
    def __init__(self):
        self.pool = None
        self.running = False
        self.task = None
        self.backfill_task = None
        self.backfill_status = {"running": False, "message": "idle", "symbols": {}, "startedAt": None, "finishedAt": None, "error": ""}
        self.micro_task = None
        self.micro_running = False
        self.micro_last_run_at = None
        self.micro_last_error = ""
        self.micro_candidates = []
        self.micro_ranking12h = []
        self.micro_positions = []
        self.last_error = ""
        self.last_run_at = None
        self.snapshots = {}

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        await self.start_micro()

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None
        await self.stop_micro()

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
        await self.stop_micro()
        if self.pool:
            await self.pool.close()

    async def start_micro(self):
        if self.micro_running:
            return
        self.micro_running = True
        self.micro_task = asyncio.create_task(self._micro_loop())

    async def stop_micro(self):
        self.micro_running = False
        if self.micro_task:
            self.micro_task.cancel()
            self.micro_task = None

    async def _micro_loop(self):
        while self.micro_running:
            try:
                await self.run_micro_once()
                self.micro_last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.micro_last_error = str(exc)
            await asyncio.sleep(CONFIG["microPollSeconds"])

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
        await self._save_candles(symbol, CONFIG["interval"], candles)
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

    async def _save_candles(self, symbol, interval, candles):
        rows = [
            (
                symbol,
                interval,
                datetime.fromtimestamp(candle["closeTime"] / 1000, tz=timezone.utc),
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle["volume"],
                CONFIG["dataSource"],
            )
            for candle in candles
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO crypto_candles(symbol,interval,ts,open,high,low,close,volume,source)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT(symbol,interval,ts) DO UPDATE SET
                   open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                   close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source""",
                rows,
            )

    async def start_backfill(self, days=90):
        if self.backfill_task and not self.backfill_task.done():
            return self.backfill_status
        self.backfill_status = {
            "running": True,
            "message": "starting",
            "symbols": {},
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "finishedAt": None,
            "error": "",
            "days": days,
        }
        self.backfill_task = asyncio.create_task(self._backfill_history(days))
        return self.backfill_status

    async def _backfill_history(self, days):
        try:
            since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
            async with httpx.AsyncClient(timeout=30) as client:
                for symbol in CONFIG["symbols"]:
                    self.backfill_status["symbols"].setdefault(symbol, {})
                    for interval in [CONFIG["interval"], CONFIG["higherInterval"]]:
                        saved = await self._backfill_symbol_interval(client, symbol, interval, since_ms)
                        self.backfill_status["symbols"][symbol][interval] = saved
            self.backfill_status["message"] = "completed"
        except Exception as exc:
            self.backfill_status["error"] = str(exc)
            self.backfill_status["message"] = "failed"
        finally:
            self.backfill_status["running"] = False
            self.backfill_status["finishedAt"] = datetime.now(timezone.utc).isoformat()

    async def _backfill_symbol_interval(self, client, symbol, interval, since_ms):
        after = None
        total = 0
        seen_oldest = None
        while True:
            candles = await fetch_history_klines(client, symbol, interval, 300, after)
            candles = dedupe_candles(candles)
            if not candles:
                break
            wanted = [candle for candle in candles if candle["closeTime"] >= since_ms]
            if wanted:
                await self._save_candles(symbol, interval, wanted)
                total += len(wanted)
            oldest = min(candle["closeTime"] for candle in candles)
            self.backfill_status["message"] = f"{symbol} {interval} saved {total}"
            self.backfill_status["symbols"].setdefault(symbol, {})[interval] = total
            if oldest <= since_ms or oldest == seen_oldest:
                break
            seen_oldest = oldest
            after = str(oldest)
            await asyncio.sleep(0.12)
        return total

    async def run_micro_once(self):
        async with httpx.AsyncClient(timeout=20) as client:
            tickers = await fetch_market_tickers(client, CONFIG["microInstType"])
            shortlist = shortlist_micro_tickers(tickers)
            states = await self._load_micro_states()
            open_count = sum(1 for state in states.values() if state.get("assetQty", 0) > 0)
            candidates = []
            positions = []
            for ticker in shortlist:
                inst_id = ticker["instId"]
                candles = await fetch_okx_candles_by_inst(client, inst_id, CONFIG["interval"], 160)
                if len(candles) < 61:
                    continue
                signal = micro_trend_signal(ticker, candles)
                state = states.get(inst_id, new_micro_state())
                price = candles[-1]["close"]
                if state.get("assetQty", 0) > 0:
                    if micro_should_exit(signal, state, price):
                        await self._micro_sell(inst_id, state, price, signal, signal["exitReason"])
                        open_count = max(0, open_count - 1)
                    else:
                        positions.append(micro_position_row(inst_id, state, price, signal))
                        await self._save_micro_state(inst_id, state)
                elif signal["buy"] and open_count < CONFIG["microMaxPositions"]:
                    await self._micro_buy(inst_id, state, price, signal)
                    open_count += 1
                    positions.append(micro_position_row(inst_id, state, price, signal))
                candidates.append(signal)
                await asyncio.sleep(0.08)
        candidates.sort(key=lambda row: (row["buy"], row["trendScore"]), reverse=True)
        ranking12h = sorted(candidates, key=lambda row: row["pct12h"], reverse=True)
        positions.sort(key=lambda row: row["unrealizedPnlPct"], reverse=True)
        self.micro_candidates = candidates[:40]
        self.micro_ranking12h = ranking12h[:40]
        self.micro_positions = positions
        self.micro_last_run_at = datetime.now(timezone.utc).isoformat()

    async def _load_micro_states(self):
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT inst_id,state FROM crypto_micro_state")
        states = {}
        for record in records:
            raw_state = record["state"]
            states[record["inst_id"]] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
        return states

    async def _save_micro_state(self, inst_id, state):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_micro_state(inst_id,state,updated_at)
                   VALUES($1,$2::jsonb,NOW())
                   ON CONFLICT(inst_id) DO UPDATE SET state=$2::jsonb, updated_at=NOW()""",
                inst_id,
                json.dumps(state),
            )

    async def _micro_buy(self, inst_id, state, price, signal):
        quote = CONFIG["microOrderQuoteSize"]
        qty = quote / price
        state.update({
            "assetQty": qty,
            "avgEntry": price,
            "entryTime": signal["time"],
            "entryReason": signal["reason"],
            "trades": state.get("trades", 0) + 1,
        })
        await self._save_micro_state(inst_id, state)
        await self._log_micro_trade(inst_id, "BUY", price, qty, quote, signal, signal["reason"])

    async def _micro_sell(self, inst_id, state, price, signal, reason):
        qty = state.get("assetQty", 0)
        quote = qty * price
        pnl = quote - qty * state.get("avgEntry", 0)
        state["assetQty"] = 0
        state["avgEntry"] = 0
        state["lastExitTime"] = signal["time"]
        state["realizedPnl"] = state.get("realizedPnl", 0) + pnl
        state["closedTrades"] = state.get("closedTrades", 0) + 1
        state["wins"] = state.get("wins", 0) + (1 if pnl > 0 else 0)
        state["trades"] = state.get("trades", 0) + 1
        await self._save_micro_state(inst_id, state)
        await self._log_micro_trade(inst_id, "SELL", price, qty, quote, signal, reason)

    async def _log_micro_trade(self, inst_id, side, price, qty, quote, signal, reason):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_micro_trades(inst_id,side,price,quantity,quote_amount,ma60,volume_ratio,pct5,pct15,reason)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                inst_id, side, price, qty, quote, signal["ma60"], signal["volumeRatio"], signal["pct5"], signal["pct15"], reason,
            )

    def status(self):
        markets = []
        for symbol in CONFIG["symbols"]:
            markets.append(self.snapshots.get(symbol) or empty_snapshot(symbol, self.running, self.last_error, self.last_run_at))
        return {"running": self.running, "markets": markets, "config": CONFIG, "lastError": self.last_error, "lastRunAt": self.last_run_at, "backfill": self.backfill_status}

    def micro_status(self):
        return {
            "running": self.micro_running,
            "lastRunAt": self.micro_last_run_at,
            "lastError": self.micro_last_error,
            "candidates": self.micro_candidates,
            "ranking12h": getattr(self, "micro_ranking12h", []),
            "positions": self.micro_positions,
            "config": CONFIG,
        }


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

    @app.get("/micro", response_class=HTMLResponse)
    async def micro_dashboard():
        return HTMLResponse(MICRO_HTML)

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

    @app.get("/api/crypto/micro")
    async def crypto_micro_status():
        return JSONResponse(crypto_bot.micro_status())

    @app.get("/api/crypto/micro/ranking12h")
    async def crypto_micro_ranking12h():
        return JSONResponse(getattr(crypto_bot, "micro_ranking12h", []))

    @app.post("/api/crypto/micro/run-once")
    async def crypto_micro_run_once():
        await crypto_bot.run_micro_once()
        return JSONResponse(crypto_bot.micro_status())

    @app.get("/api/crypto/micro/trades")
    async def crypto_micro_trades(inst_id: str = Query("", max_length=30)):
        sql = "SELECT ts,inst_id,side,price,quantity,quote_amount,ma60,volume_ratio,pct5,pct15,reason FROM crypto_micro_trades"
        args = []
        if inst_id:
            sql += " WHERE inst_id=$1"
            args.append(inst_id.upper())
        sql += " ORDER BY ts DESC LIMIT 120"
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        rows = annotate_micro_trade_pnl(rows)
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.post("/api/crypto/backfill")
    async def crypto_backfill(days: int = Query(90, ge=1, le=365)):
        status = await crypto_bot.start_backfill(days)
        return JSONResponse(status)

    @app.get("/api/crypto/backfill")
    async def crypto_backfill_status():
        return JSONResponse(crypto_bot.backfill_status)

    @app.get("/api/crypto/trades")
    async def crypto_trades(symbol: str = Query("", max_length=20), strategy: str = Query("", max_length=80)):
        sql = "SELECT ts,symbol,strategy,side,price,quantity,quote_amount,reason FROM crypto_trades"
        args = []
        if symbol:
            sql += " WHERE symbol=$1"
            args.append(symbol.upper())
        if strategy:
            sql += " AND strategy=$2" if args else " WHERE strategy=$1"
            args.append(strategy)
        sql += " ORDER BY ts DESC LIMIT 100"
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        rows = annotate_trade_pnl(rows)
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.get("/api/crypto/candles")
    async def crypto_candles(symbol: str = Query("BTCUSDT", max_length=20), interval: str = Query("5m", max_length=10), limit: int = Query(300, ge=1, le=2000)):
        async with crypto_bot.pool.acquire() as conn:
            rows = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT symbol,interval,ts,open,high,low,close,volume,source
                       FROM crypto_candles
                       WHERE symbol=$1 AND interval=$2
                       ORDER BY ts DESC LIMIT $3""",
                    symbol.upper(),
                    interval,
                    limit,
                )
            ]
        rows.reverse()
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.get("/api/crypto/performance")
    async def crypto_performance(symbol: str = Query("", max_length=20)):
        wanted_symbols = [symbol.upper()] if symbol else CONFIG["symbols"]
        async with crypto_bot.pool.acquire() as conn:
            state_rows = [
                dict(row)
                for row in await conn.fetch(
                    "SELECT symbol,strategy,state,updated_at FROM crypto_state WHERE symbol = ANY($1::text[])",
                    wanted_symbols,
                )
            ]
            candle_rows = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT DISTINCT ON (symbol) symbol, close, ts
                       FROM crypto_candles
                       WHERE interval=$1 AND symbol = ANY($2::text[])
                       ORDER BY symbol, ts DESC""",
                    CONFIG["interval"],
                    wanted_symbols,
                )
            ]
        state_map = {}
        updated_map = {}
        for row in state_rows:
            raw_state = row["state"]
            key = (row["symbol"], row["strategy"])
            state_map[key] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
            updated_map[key] = row["updated_at"]
        price_map = {row["symbol"]: float(row["close"]) for row in candle_rows}
        price_time_map = {row["symbol"]: row["ts"] for row in candle_rows}
        rows = []
        for market_symbol in wanted_symbols:
            snapshot = crypto_bot.snapshots.get(market_symbol)
            latest_price = (snapshot["lastPrice"] if snapshot else 0) or price_map.get(market_symbol, 0)
            for strategy in STRATEGIES:
                key = (market_symbol, strategy["id"])
                account = state_map.get(key) or new_account()
                item = snapshot_row(strategy, account, latest_price)
                item["symbol"] = market_symbol
                item["closedTrades"] = account.get("closedTrades", 0)
                item["updatedAt"] = updated_map[key].isoformat() if key in updated_map else None
                item["priceTime"] = price_time_map[market_symbol].isoformat() if market_symbol in price_time_map else None
                rows.append(item)
        rows.sort(key=lambda row: row["returnPct"], reverse=True)
        return JSONResponse(rows)

    @app.get("/api/crypto/backtest")
    async def crypto_backtest(days: int = Query(90, ge=1, le=365), symbol: str = Query("", max_length=20)):
        wanted_symbols = [symbol.upper()] if symbol else CONFIG["symbols"]
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = []
        async with crypto_bot.pool.acquire() as conn:
            for market_symbol in wanted_symbols:
                candles = [
                    candle_from_db(row)
                    for row in await conn.fetch(
                        """SELECT ts,open,high,low,close,volume FROM crypto_candles
                           WHERE symbol=$1 AND interval=$2 AND ts >= $3
                           ORDER BY ts ASC""",
                        market_symbol,
                        CONFIG["interval"],
                        since,
                    )
                ]
                higher = [
                    candle_from_db(row)
                    for row in await conn.fetch(
                        """SELECT ts,open,high,low,close,volume FROM crypto_candles
                           WHERE symbol=$1 AND interval=$2 AND ts >= $3
                           ORDER BY ts ASC""",
                        market_symbol,
                        CONFIG["higherInterval"],
                        since - timedelta(days=2),
                    )
                ]
                results.extend(backtest_symbol(market_symbol, candles, higher))
        results.sort(key=lambda row: row["returnPct"], reverse=True)
        return JSONResponse({"days": days, "rows": results})

    @app.get("/api/crypto/strategy")
    async def crypto_strategy_detail(symbol: str = Query(..., max_length=20), strategy: str = Query(..., max_length=80)):
        symbol = symbol.upper()
        strategy_def = next((item for item in STRATEGIES if item["id"] == strategy), None)
        if not strategy_def:
            return JSONResponse({"error": "unknown_strategy"}, status_code=404)
        async with crypto_bot.pool.acquire() as conn:
            state_row = await conn.fetchrow(
                "SELECT state,updated_at FROM crypto_state WHERE symbol=$1 AND strategy=$2",
                symbol,
                strategy,
            )
            candle_row = await conn.fetchrow(
                """SELECT close, ts FROM crypto_candles
                   WHERE symbol=$1 AND interval=$2
                   ORDER BY ts DESC LIMIT 1""",
                symbol,
                CONFIG["interval"],
            )
            trades = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT ts,symbol,strategy,side,price,quantity,quote_amount,reason
                       FROM crypto_trades
                       WHERE symbol=$1 AND strategy=$2
                       ORDER BY ts DESC LIMIT 80""",
                    symbol,
                    strategy,
                )
            ]
            signals = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT ts,price,signal,reason,action,equity,return_pct
                       FROM crypto_signals
                       WHERE symbol=$1 AND strategy=$2
                       ORDER BY ts DESC LIMIT 30""",
                    symbol,
                    strategy,
                )
            ]
        account = new_account()
        updated_at = None
        if state_row:
            raw_state = state_row["state"]
            account = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
            updated_at = state_row["updated_at"]
        snapshot = crypto_bot.snapshots.get(symbol)
        latest_price = (snapshot["lastPrice"] if snapshot else 0) or (float(candle_row["close"]) if candle_row else 0)
        performance = snapshot_row(strategy_def, account, latest_price)
        performance["symbol"] = symbol
        performance["closedTrades"] = account.get("closedTrades", 0)
        performance["updatedAt"] = updated_at.isoformat() if updated_at else None
        performance["priceTime"] = candle_row["ts"].isoformat() if candle_row else None
        trades = annotate_trade_pnl(trades)
        for row in trades:
            row["ts"] = row["ts"].isoformat()
        for row in signals:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse({"performance": performance, "trades": trades, "signals": signals})


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


async def fetch_history_klines(client, symbol, interval, limit, after=None):
    inst_id = to_okx_inst_id(symbol)
    params = {"instId": inst_id, "bar": interval, "limit": str(limit)}
    if after:
        params["after"] = after
    resp = await client.get(f"{OKX_BASE}/api/v5/market/history-candles", params=params)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX history candles error: {payload}")
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


async def fetch_market_tickers(client, inst_type):
    resp = await client.get(f"{OKX_BASE}/api/v5/market/tickers", params={"instType": inst_type})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX tickers error: {payload}")
    return payload["data"]


async def fetch_okx_candles_by_inst(client, inst_id, interval, limit):
    resp = await client.get(
        f"{OKX_BASE}/api/v5/market/candles",
        params={"instId": inst_id, "bar": interval, "limit": str(limit)},
    )
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


def shortlist_micro_tickers(tickers):
    rows = []
    for ticker in tickers:
        inst_id = ticker.get("instId", "")
        parts = inst_id.split("-")
        if not is_micro_usdt_inst(parts):
            continue
        quote_vol = safe_float(ticker.get("volCcy24h"))
        if quote_vol < CONFIG["microMinQuoteVolume24h"] or quote_vol > CONFIG["microMaxQuoteVolume24h"]:
            continue
        last = safe_float(ticker.get("last"))
        open24h = safe_float(ticker.get("open24h"))
        if last <= 0 or open24h <= 0:
            continue
        pct24 = ((last - open24h) / open24h) * 100
        if pct24 < -15 or pct24 > 120:
            continue
        rows.append({**ticker, "_quoteVol": quote_vol, "_pct24": pct24})
    rows.sort(key=lambda row: (row["_pct24"], row["_quoteVol"]), reverse=True)
    return rows[:60]


def is_micro_usdt_inst(parts):
    if len(parts) == 2:
        base, quote = parts
        return quote == "USDT" and base not in MICRO_EXCLUDED_BASES
    if len(parts) == 3:
        base, quote, contract = parts
        return quote == "USDT" and contract == "SWAP" and base not in MICRO_EXCLUDED_BASES
    return False


def micro_trend_signal(ticker, candles):
    close = candles[-1]["close"]
    prev_close = candles[-2]["close"]
    close_15 = candles[-4]["close"] if len(candles) >= 4 else prev_close
    close_1h = candles[-13]["close"] if len(candles) >= 13 else prev_close
    close_12h = candles[-145]["close"] if len(candles) >= 145 else candles[0]["close"]
    pct5 = ((close - prev_close) / prev_close) * 100 if prev_close else 0
    pct15 = ((close - close_15) / close_15) * 100 if close_15 else 0
    pct1h = ((close - close_1h) / close_1h) * 100 if close_1h else 0
    pct12h = ((close - close_12h) / close_12h) * 100 if close_12h else 0
    volumes = [c["volume"] for c in candles]
    recent_vol = sma(volumes, 6) or candles[-1]["volume"]
    base_vol = sma(volumes[-36:-6], 30) or 0
    volume_ratio = recent_vol / base_vol if base_vol else 0
    prior_high = max(c["high"] for c in candles[-25:-1])
    closes = [c["close"] for c in candles]
    ma5 = sma(closes, 5) or close
    ma20 = sma(closes, 20) or close
    ma60 = sma(closes, 60) or close
    ma20_prev = sma(closes[:-12], 20) or ma20
    ma60_prev = sma(closes[:-12], 60) or ma60
    ma20_slope = ((ma20 - ma20_prev) / ma20_prev) * 100 if ma20_prev else 0
    ma60_slope = ((ma60 - ma60_prev) / ma60_prev) * 100 if ma60_prev else 0
    stacked = close > ma5 > ma20 > ma60
    breakout = close > prior_high
    volume_rising = volume_ratio >= CONFIG["microTrendVolumeRatio"]
    trend_ok = stacked and ma20_slope > 0 and ma60_slope >= 0 and pct1h >= CONFIG["microTrendMinPct1h"] and pct15 >= CONFIG["microTrendMinPct15m"]
    buy = (
        trend_ok
        and volume_rising
        and breakout
    )
    trend_score = (pct1h * 1.2) + (pct15 * 0.8) + (volume_ratio * 2) + (ma20_slope * 3) + (ma60_slope * 2)
    exit_reason = ""
    if close < ma20:
        exit_reason = "close_below_ma20"
    elif ma20 < ma60:
        exit_reason = "ma20_below_ma60"
    return {
        "instId": ticker["instId"],
        "price": rnd(close, 8),
        "pct5": rnd(pct5),
        "pct15": rnd(pct15),
        "pct1h": rnd(pct1h),
        "pct12h": rnd(pct12h),
        "pct24": rnd(ticker.get("_pct24", 0)),
        "quoteVolume24h": rnd(ticker.get("_quoteVol", 0)),
        "volumeRatio": rnd(volume_ratio),
        "ma5": rnd(ma5, 8),
        "ma20": rnd(ma20, 8),
        "ma60": rnd(ma60, 8),
        "ma20Slope": rnd(ma20_slope),
        "ma60Slope": rnd(ma60_slope),
        "stacked": stacked,
        "breakout": breakout,
        "trendScore": rnd(trend_score),
        "exitReason": exit_reason,
        "buy": buy,
        "time": candles[-1]["closeTime"],
        "reason": "ma_stack_volume_trend" if buy else "watch",
    }


def micro_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if entry and price <= entry * (1 - CONFIG["microStopLossPct"] / 100):
        signal["exitReason"] = "stop_loss_1pct"
    return bool(signal.get("exitReason"))


def new_micro_state():
    return {"assetQty": 0.0, "avgEntry": 0.0, "realizedPnl": 0.0, "trades": 0, "closedTrades": 0, "wins": 0}


def micro_position_row(inst_id, state, price, signal):
    entry = state.get("avgEntry", 0)
    qty = state.get("assetQty", 0)
    value = qty * price
    unreal = (price - entry) * qty if entry else 0
    return {
        "instId": inst_id,
        "price": rnd(price, 8),
        "avgEntry": rnd(entry, 8),
        "quantity": rnd(qty, 8),
        "positionValue": rnd(value),
        "unrealizedPnl": rnd(unreal),
        "unrealizedPnlPct": rnd(((price - entry) / entry) * 100 if entry else 0),
        "ma20": signal["ma20"],
        "ma60": signal["ma60"],
        "distanceToMa20Pct": rnd(((price - signal["ma20"]) / signal["ma20"]) * 100 if signal["ma20"] else 0),
        "distanceToMa60Pct": rnd(((price - signal["ma60"]) / signal["ma60"]) * 100 if signal["ma60"] else 0),
        "realizedPnl": rnd(state.get("realizedPnl", 0)),
        "trades": state.get("trades", 0),
        "closedTrades": state.get("closedTrades", 0),
        "winRate": rnd((state.get("wins", 0) / state.get("closedTrades", 0)) * 100 if state.get("closedTrades", 0) else 0),
    }


def annotate_micro_trade_pnl(rows):
    annotated = []
    open_lots = {}
    for row in reversed(rows):
        key = row["inst_id"]
        item = dict(row)
        item["pnl"] = None
        item["pnlPct"] = None
        if row["side"] == "BUY":
            open_lots[key] = row
        elif row["side"] == "SELL" and key in open_lots:
            buy_row = open_lots.pop(key)
            entry = float(buy_row["price"])
            exit_price = float(row["price"])
            quantity = float(row["quantity"])
            pnl = (exit_price - entry) * quantity
            item["entryPrice"] = entry
            item["pnl"] = rnd(pnl)
            item["pnlPct"] = rnd(((exit_price - entry) / entry) * 100 if entry else 0)
        annotated.append(item)
    return list(reversed(annotated))


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def dedupe_candles(candles):
    by_time = {candle["closeTime"]: candle for candle in candles}
    return [by_time[key] for key in sorted(by_time)]


def candle_from_db(row):
    ts_ms = int(row["ts"].timestamp() * 1000)
    return {
        "time": ts_ms,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "closeTime": ts_ms,
    }


def annotate_trade_pnl(rows):
    annotated = []
    open_lots = {}
    for row in reversed(rows):
        key = (row["symbol"], row["strategy"])
        item = dict(row)
        item["pnl"] = None
        item["pnlPct"] = None
        if row["side"] == "BUY":
            open_lots[key] = row
        elif row["side"] == "SELL" and key in open_lots:
            buy_row = open_lots.pop(key)
            entry = float(buy_row["price"])
            exit_price = float(row["price"])
            quantity = float(row["quantity"])
            pnl = (exit_price - entry) * quantity
            item["entryPrice"] = entry
            item["pnl"] = rnd(pnl)
            item["pnlPct"] = rnd(((exit_price - entry) / entry) * 100 if entry else 0)
        annotated.append(item)
    return list(reversed(annotated))


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


def backtest_symbol(symbol, candles, higher):
    if len(candles) < 80 or len(higher) < 40:
        return [
            {
                "symbol": symbol,
                "id": strategy["id"],
                "name": strategy["name"],
                "description": strategy["description"],
                "candles": len(candles),
                "higherCandles": len(higher),
                "error": "not_enough_candles",
                **snapshot_row(strategy, new_account(), candles[-1]["close"] if candles else 0),
            }
            for strategy in STRATEGIES
        ]
    accounts = {strategy["id"]: new_account() for strategy in STRATEGIES}
    higher_index = 0
    for index, candle in enumerate(candles):
        while higher_index + 1 < len(higher) and higher[higher_index + 1]["closeTime"] <= candle["closeTime"]:
            higher_index += 1
        if index < 60 or higher_index < 30:
            continue
        window = candles[max(0, index - 220):index + 1]
        higher_window = higher[max(0, higher_index - 220):higher_index + 1]
        price = candle["close"]
        close_time = candle["closeTime"]
        for strategy in STRATEGIES:
            account = accounts[strategy["id"]]
            refresh_daily_limit(account, close_time)
            decision = decide(strategy["id"], window, higher_window, account)
            decision = with_risk_exit(decision, account, price)
            if decision["signal"] == "BUY" and account["assetQty"] <= 0 and can_enter(account, close_time):
                quote = min(account["cash"], CONFIG["orderQuoteSize"])
                qty = quote / price
                account["cash"] -= quote
                account["assetQty"] += qty
                account["avgEntry"] = price
                account["entryCountToday"] += 1
                account["trades"] += 1
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
            equity = account["cash"] + account["assetQty"] * price
            account["peakEquity"] = max(account["peakEquity"], equity)
            if account["peakEquity"] > 0:
                account["maxDrawdownPct"] = max(account["maxDrawdownPct"], ((account["peakEquity"] - equity) / account["peakEquity"]) * 100)
            account["lastSignal"] = decision["signal"]
            account["lastReason"] = decision["reason"]
            account["lastAction"] = "backtest"
            account["lastCandleCloseTime"] = close_time
    last_price = candles[-1]["close"]
    rows = []
    for strategy in STRATEGIES:
        item = snapshot_row(strategy, accounts[strategy["id"]], last_price)
        item["symbol"] = symbol
        item["closedTrades"] = accounts[strategy["id"]].get("closedTrades", 0)
        item["candles"] = len(candles)
        item["higherCandles"] = len(higher)
        rows.append(item)
    return rows


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
<style>body{margin:0;background:#f5f7f4;color:#18201f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0}.controls{display:flex;gap:8px}button{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:700;cursor:pointer}main{max-width:1280px;margin:auto;padding:24px}.tabs{display:flex;gap:10px;margin-bottom:16px}.tabs button{min-width:120px}.active{border-color:#2867b2;box-shadow:inset 0 0 0 1px #2867b2}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel,.card{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}canvas{width:100%;height:280px;border:1px solid #dce3df;border-radius:8px;background:#fbfcfb}.cards{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:12px}.card{padding:14px;cursor:pointer}.card.pos{border-color:rgba(22,131,95,.55);background:#fbfffc}.card.selected,.pick.selected td{border-color:#2867b2;background:#f3f8ff}.pick{cursor:pointer}.position{border:1px solid #dce3df;border-radius:8px;padding:10px;margin:10px 0;background:#f8faf8}.position.on{background:#effaf4}.stat{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #dce3df;padding-top:8px;margin-top:8px;font-size:13px}.detailgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}.good{color:#16835f}.bad{color:#c53b3b}table{width:100%;min-width:860px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}@media(max-width:900px){.grid,.cards,.detailgrid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid,.cards,.detailgrid{grid-template-columns:1fr}.top{align-items:flex-start}}</style></head>
<body><header class="top"><div><h1>Crypto Strategy Lab</h1><p id="sub">Loading...</p></div><div class="controls"><button id="run">Run</button><button id="toggle">Start</button><button id="microScan">Micro Scan</button><button id="backfill">Backfill 90d</button><button id="backtest">Backtest</button></div></header><main><nav id="tabs" class="tabs"></nav><section class="grid"><div class="metric"><span>Last Price</span><strong id="price">--</strong></div><div class="metric"><span>Leader</span><strong id="leader">--</strong></div><div class="metric"><span>Best Return</span><strong id="ret">--</strong></div><div class="metric"><span>Mode</span><strong>Paper</strong></div></section><section class="panel"><h2>5m Candles</h2><p id="last">Waiting</p><canvas id="chart"></canvas></section><section><h2>Strategy Ranking</h2><div id="cards" class="cards"></div></section><section class="panel"><h2>Small Cap Breakout Radar</h2><p id="microStatus">Waiting for scan.</p><div id="microPositions"></div><div id="microCandidates"></div><div id="microTrades"></div></section><section class="panel"><h2>Selected Strategy</h2><div id="detail"><p>Click a strategy card or table row to inspect it.</p></div></section><section class="panel"><h2>Backtest Performance</h2><p id="backfillStatus">Historical data status: idle.</p><div id="backtestRows"></div></section><section class="panel"><h2>Strategy Performance</h2><p>All 15 paper-trading combinations are ranked by current return, including realized and unrealized P/L.</p><div id="performance"></div></section><section class="panel"><h2>Trade History</h2><p>Past entries/exits are stored in lighto-tracker-db. Open positions and unrealized P/L are shown above.</p><div id="trades"></div></section></main>
<script>
let state={data:null,symbol:"",selected:null}; const $=s=>document.querySelector(s);
$("#run").onclick=()=>post("/api/crypto/run-once"); $("#toggle").onclick=()=>post(state.data?.running?"/api/crypto/stop":"/api/crypto/start");
$("#microScan").onclick=()=>runMicroScan();
$("#backfill").onclick=async()=>{let s=await (await fetch("/api/crypto/backfill?days=90",{method:"POST"})).json();renderBackfill(s);}
$("#backtest").onclick=()=>loadBacktest();
setInterval(load,10000); load();
async function load(){state.data=await (await fetch("/api/crypto/status")).json(); render(); if(state.data.backfill)renderBackfill(state.data.backfill); loadMicro();}
async function post(url){state.data=await (await fetch(url,{method:"POST"})).json(); render();}
function markets(){return state.data?.markets||[]} function market(){let ms=markets(); if(!state.symbol&&ms[0])state.symbol=ms[0].config.symbol; return ms.find(m=>m.config.symbol===state.symbol)||ms[0];}
async function loadTrades(){let m=market(); if(!m)return; let rows=await (await fetch(`/api/crypto/trades?symbol=${m.config.symbol}`)).json(); renderTrades(rows);}
async function loadPerformance(){let rows=await (await fetch("/api/crypto/performance")).json(); renderPerformance(rows);}
function renderTrades(rows){if(!rows.length){$("#trades").innerHTML='<p>No trades yet for this market.</p>';return} $("#trades").innerHTML=`<table><thead><tr><th>Time</th><th>Side</th><th>Strategy</th><th>Price</th><th>Qty</th><th>Amount</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${r.strategy}</td><td>${money(r.price)}</td><td>${qty(r.quantity)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
function render(){let m=market(); if(!m)return; let leader=m.strategies[0]; $("#sub").textContent=`${m.config.symbol} · ${m.config.dataSource||'OKX'} · 5m trigger / 15m structure`; $("#price").textContent=money(m.lastPrice); $("#leader").textContent=leader?.name||"--"; $("#ret").textContent=pct(leader?.returnPct||0); $("#ret").className=tone(leader?.returnPct||0); $("#toggle").textContent=state.data.running?"Stop":"Start"; $("#last").textContent=m.updatedAt?`Last update: ${new Date(m.updatedAt).toLocaleString()}`:"Waiting for first update"; tabs(); cards(m.strategies,m.lastPrice); chart(m.candles||[]); loadTrades(); loadPerformance(); if(state.selected)loadDetail();}
function tabs(){ $("#tabs").innerHTML=markets().map(m=>`<button class="${m.config.symbol===state.symbol?'active':''}" data-s="${m.config.symbol}">${m.config.symbol.replace('USDT','')}</button>`).join(""); document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{state.symbol=b.dataset.s;state.selected=null;$("#detail").innerHTML='<p>Click a strategy card or table row to inspect it.</p>';render();});}
function cards(strats, price){let m=market(); $("#cards").innerHTML=strats.map((s,i)=>{let pv=s.positionValue??s.assetQty*price; let cost=s.assetQty*s.avgEntry; let pnl=cost?((pv-cost)/cost*100):0; let sel=state.selected&&state.selected.symbol===m.config.symbol&&state.selected.strategy===s.id; return `<article class="card ${s.inPosition?'pos':''} ${sel?'selected':''}" data-symbol="${m.config.symbol}" data-strategy="${s.id}"><h3>${s.name}</h3><span class="label">${s.id}</span><p>${s.description}</p><div class="position ${s.inPosition?'on':''}"><span class="label">Position</span><strong>${s.inPosition?'Long '+money(pv):'Flat'}</strong>${s.inPosition?`<div>Qty ${qty(s.assetQty)}</div><div>Entry ${money(s.avgEntry)}</div><div class="${tone(pnl)}">P/L ${pct(pnl)}</div>`:''}</div>${stat('Equity',money(s.equity))}${stat('Return',`<span class="${tone(s.returnPct)}">${pct(s.returnPct)}</span>`)}${stat('Trades',s.trades)}${stat('Signal',s.lastSignal)}${stat('Reason',s.lastReason)}</article>`}).join(""); document.querySelectorAll(".card[data-strategy]").forEach(el=>el.onclick=()=>selectStrategy(el.dataset.symbol,el.dataset.strategy));}
function renderPerformance(rows){if(!rows.length){$("#performance").innerHTML='<p>No strategy state yet.</p>';return} $("#performance").innerHTML=`<table><thead><tr><th>Rank</th><th>Market</th><th>Strategy</th><th>Equity</th><th>Return</th><th>Realized</th><th>Unrealized</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Position</th></tr></thead><tbody>${rows.map((r,i)=>{let sel=state.selected&&state.selected.symbol===r.symbol&&state.selected.strategy===r.id; return `<tr class="pick ${sel?'selected':''}" data-symbol="${r.symbol}" data-strategy="${r.id}"><td>${i+1}</td><td>${r.symbol.replace('USDT','')}</td><td>${r.name}<br><span class="label">${r.id}</span></td><td>${money(r.equity)}</td><td class="${tone(r.returnPct)}">${pct(r.returnPct)}</td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedPnlPct)}</td><td>${r.trades} / ${r.closedTrades}</td><td>${pct(r.winRate)}</td><td class="bad">${pct(-Math.abs(r.maxDrawdownPct||0))}</td><td>${r.inPosition?'Long '+money(r.positionValue):'Flat'}</td></tr>`}).join('')}</tbody></table>`; document.querySelectorAll(".pick[data-strategy]").forEach(el=>el.onclick=()=>selectStrategy(el.dataset.symbol,el.dataset.strategy));}
async function selectStrategy(symbol,strategy){state.selected={symbol,strategy};state.symbol=symbol;render();await loadDetail();}
async function loadDetail(){let s=state.selected;if(!s)return;let data=await (await fetch(`/api/crypto/strategy?symbol=${s.symbol}&strategy=${s.strategy}`)).json();renderDetail(data);}
function renderDetail(data){let p=data.performance;if(!p){$("#detail").innerHTML='<p>No detail found.</p>';return} $("#detail").innerHTML=`<h3>${p.symbol.replace('USDT','')} · ${p.name}</h3><div class="detailgrid"><div class="metric"><span>Equity</span><strong>${money(p.equity)}</strong></div><div class="metric"><span>Return</span><strong class="${tone(p.returnPct)}">${pct(p.returnPct)}</strong></div><div class="metric"><span>Realized</span><strong class="${tone(p.realizedPnl)}">${money(p.realizedPnl)}</strong></div><div class="metric"><span>Unrealized</span><strong class="${tone(p.unrealizedPnl)}">${money(p.unrealizedPnl)}</strong></div></div><div class="detailgrid"><div>${stat('Position',p.inPosition?'Long '+money(p.positionValue):'Flat')}${stat('Qty',qty(p.assetQty))}${stat('Entry',money(p.avgEntry))}</div><div>${stat('Trades',p.trades+' / '+p.closedTrades)}${stat('Win Rate',pct(p.winRate))}${stat('Max DD',pct(-Math.abs(p.maxDrawdownPct||0)))}</div><div>${stat('Signal',p.lastSignal)}${stat('Action',p.lastAction)}${stat('Reason',p.lastReason)}</div><div>${stat('Updated',p.updatedAt?new Date(p.updatedAt).toLocaleString():'--')}${stat('Price Time',p.priceTime?new Date(p.priceTime).toLocaleString():'--')}</div></div><h3>Strategy Trades</h3>${miniTrades(data.trades)}<h3>Recent Signals</h3>${miniSignals(data.signals)}`;}
function miniTrades(rows){if(!rows.length)return '<p>No trades for this strategy yet.</p>';return `<table><thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Qty</th><th>Amount</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${money(r.price)}</td><td>${qty(r.quantity)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
function miniSignals(rows){if(!rows.length)return '<p>No signals yet.</p>';return `<table><thead><tr><th>Time</th><th>Signal</th><th>Action</th><th>Price</th><th>Equity</th><th>Return</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td>${r.signal}</td><td>${r.action}</td><td>${money(r.price)}</td><td>${money(r.equity)}</td><td class="${tone(r.return_pct)}">${pct(r.return_pct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
async function loadBackfill(){let s=await (await fetch("/api/crypto/backfill")).json();renderBackfill(s);}
function renderBackfill(s){let parts=Object.entries(s.symbols||{}).map(([sym,vals])=>`${sym}: 5m ${vals["5m"]||0}, 15m ${vals["15m"]||0}`).join(" | ");$("#backfillStatus").textContent=`Historical data status: ${s.message||"idle"}${s.running?" (running)":""}${parts?" · "+parts:""}`;}
async function loadBacktest(){await loadBackfill();$("#backtestRows").innerHTML="<p>Running backtest...</p>";let data=await (await fetch("/api/crypto/backtest?days=90")).json();renderBacktest(data.rows||[]);}
function renderBacktest(rows){if(!rows.length){$("#backtestRows").innerHTML="<p>No backtest rows yet. Run Backfill 90d first.</p>";return}$("#backtestRows").innerHTML=`<table><thead><tr><th>Rank</th><th>Market</th><th>Strategy</th><th>Return</th><th>Equity</th><th>Realized</th><th>Unrealized</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Candles</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${i+1}</td><td>${r.symbol.replace("USDT","")}</td><td>${r.name}<br><span class="label">${r.id}</span></td><td class="${tone(r.returnPct)}">${pct(r.returnPct)}</td><td>${money(r.equity)}</td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)}</td><td>${r.trades} / ${r.closedTrades}</td><td>${pct(r.winRate)}</td><td class="bad">${pct(-Math.abs(r.maxDrawdownPct||0))}</td><td>${r.candles||0} / ${r.higherCandles||0}</td></tr>`).join("")}</tbody></table>`}
async function runMicroScan(){const data=await (await fetch("/api/crypto/micro/run-once",{method:"POST"})).json();renderMicro(data);await loadMicroTrades();}
async function loadMicro(){const data=await (await fetch("/api/crypto/micro")).json();renderMicro(data);await loadMicroTrades();}
function renderMicro(data){$("#microStatus").textContent=`Last scan: ${data.lastRunAt?new Date(data.lastRunAt).toLocaleString():"waiting"} - ${data.running?"running":"stopped"}${data.lastError?" - "+data.lastError:""}`;renderMicroPositions(data.positions||[]);renderMicroCandidates(data.ranking12h||data.candidates||[]);}
function renderMicroPositions(rows){if(!rows.length){$("#microPositions").innerHTML="<h3>Open Micro Positions</h3><p>No open breakout positions.</p>";return}$("#microPositions").innerHTML=`<h3>Open Micro Positions</h3><table><thead><tr><th>Coin</th><th>Entry</th><th>Price</th><th>MA60 Stop</th><th>Distance</th><th>Unrealized</th><th>Trades</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.instId}</td><td>${money(r.avgEntry)}</td><td>${money(r.price)}</td><td>${money(r.ma60)}</td><td class="${tone(r.distanceToMa60Pct)}">${pct(r.distanceToMa60Pct)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedPnlPct)}</td><td>${r.trades} / ${r.closedTrades}</td></tr>`).join("")}</tbody></table>`}
function renderMicroCandidates(rows){if(!rows.length){$("#microCandidates").innerHTML="<h3>12h Ranking Watchlist</h3><p>No candidates yet.</p>";return}$("#microCandidates").innerHTML=`<h3>12h Ranking Watchlist</h3><table><thead><tr><th>Coin</th><th>Buy</th><th>Price</th><th>12h</th><th>1h</th><th>15m</th><th>Vol x</th><th>24h Vol</th><th>MA60</th></tr></thead><tbody>${rows.slice(0,30).map(r=>`<tr><td>${r.instId}</td><td class="${r.buy?'good':'bad'}">${r.buy?'YES':'watch'}</td><td>${money(r.price)}</td><td class="${tone(r.pct12h)}">${pct(r.pct12h)}</td><td class="${tone(r.pct1h)}">${pct(r.pct1h)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td>${Number(r.volumeRatio||0).toFixed(2)}</td><td>${money(r.quoteVolume24h)}</td><td>${money(r.ma60)}</td></tr>`).join("")}</tbody></table>`}
async function loadMicroTrades(){const rows=await (await fetch("/api/crypto/micro/trades")).json();renderMicroTrades(rows);}
function renderMicroTrades(rows){if(!rows.length){$("#microTrades").innerHTML="<h3>Micro Trades</h3><p>No micro trades yet.</p>";return}$("#microTrades").innerHTML=`<h3>Micro Trades</h3><table><thead><tr><th>Time</th><th>Coin</th><th>Side</th><th>Price</th><th>MA60</th><th>Amount</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.slice(0,40).map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td>${r.inst_id}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${money(r.price)}</td><td>${money(r.ma60)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join("")}</tbody></table>`}
function stat(k,v){return `<div class="stat"><span>${k}</span><strong>${v}</strong></div>`} function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2})} function qty(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:8})} function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`} function tone(v){return Number(v)>=0?'good':'bad'}
function chart(c){const canvas=$("#chart"),r=devicePixelRatio||1,rect=canvas.getBoundingClientRect();canvas.width=Math.max(640,rect.width*r);canvas.height=280*r;const x=canvas.getContext('2d');x.scale(r,r);x.clearRect(0,0,rect.width,280);if(!c.length){x.fillText('Waiting for candles',18,32);return}let hi=Math.max(...c.map(k=>k.high)),lo=Math.min(...c.map(k=>k.low)),span=Math.max(1,hi-lo),w=(rect.width-64)/c.length;function y(v){return 18+((hi-v)/span)*(238)};c.forEach((k,i)=>{let cx=16+i*w+w/2,up=k.close>=k.open;x.strokeStyle=x.fillStyle=up?'#16835f':'#c53b3b';x.beginPath();x.moveTo(cx,y(k.high));x.lineTo(cx,y(k.low));x.stroke();x.fillRect(cx-w*.25,Math.min(y(k.open),y(k.close)),Math.max(2,w*.5),Math.max(2,Math.abs(y(k.close)-y(k.open))))});}
</script></body></html>"""


MICRO_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Small Cap Radar</title>
<style>body{margin:0;background:#f6f7f4;color:#19211f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0;z-index:2}.controls{display:flex;gap:8px;flex-wrap:wrap}button,a.btn{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:700;cursor:pointer;color:#19211f;text-decoration:none;display:inline-flex;align-items:center}main{max-width:1280px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}.good{color:#16835f}.bad{color:#c53b3b}table{width:100%;min-width:980px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}</style></head>
<body><header class="top"><div><h1>Small Cap Perp Radar</h1><p id="status">Loading...</p></div><div class="controls"><button id="scan">Scan Now</button><a class="btn" href="/crypto">Strategy Lab</a></div></header><main><section class="grid"><div class="metric"><span>Market</span><strong id="marketType">--</strong></div><div class="metric"><span>12h Ranking</span><strong id="watchCount">--</strong></div><div class="metric"><span>Positions</span><strong id="posCount">--</strong></div><div class="metric"><span>Last Scan</span><strong id="lastScan">--</strong></div></section><section class="panel"><h2>12h Gain Ranking</h2><p>Uses OKX USDT perpetual ranking, then computes 12h gain from 5m candles and checks MA trend state.</p><div id="candidates"></div></section><section class="panel"><h2>Open Positions</h2><p>Paper positions enter on MA trend plus rising volume, then exit on close below MA20 or MA20 crossing below MA60.</p><div id="positions"></div></section><section class="panel"><h2>Entry / Exit Log</h2><div id="trades"></div></section></main>
<script>
const $=s=>document.querySelector(s);
$("#scan").onclick=()=>scan();
setInterval(load,10000); load();
async function load(){const data=await (await fetch("/api/crypto/micro")).json();render(data);await loadTrades();}
async function scan(){$("#status").textContent="Scanning...";const data=await (await fetch("/api/crypto/micro/run-once",{method:"POST"})).json();render(data);await loadTrades();}
function render(data){let ranking=data.ranking12h||data.candidates||[];$("#marketType").textContent=data.config?.microInstType||"SWAP";$("#watchCount").textContent=ranking.length;$("#posCount").textContent=(data.positions||[]).length;$("#lastScan").textContent=data.lastRunAt?new Date(data.lastRunAt).toLocaleTimeString():"--";$("#status").textContent=`${data.running?"Running":"Stopped"} - ${data.lastRunAt?new Date(data.lastRunAt).toLocaleString():"Waiting"}${data.lastError?" - "+data.lastError:""}`;renderCandidates(ranking);renderPositions(data.positions||[]);}
function renderCandidates(rows){if(!rows.length){$("#candidates").innerHTML="<p>No ranking data yet.</p>";return}$("#candidates").innerHTML=`<table><thead><tr><th>Rank</th><th>Coin</th><th>Status</th><th>Price</th><th>12h</th><th>1h</th><th>15m</th><th>Vol x</th><th>MA5</th><th>MA20</th><th>MA60</th><th>Score</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${i+1}</td><td><strong>${r.instId}</strong></td><td class="${r.buy?'good':'bad'}">${r.buy?'BUY SIGNAL':'watch'}</td><td>${money(r.price)}</td><td class="${tone(r.pct12h)}">${pct(r.pct12h)}</td><td class="${tone(r.pct1h)}">${pct(r.pct1h)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td>${Number(r.volumeRatio||0).toFixed(2)}</td><td>${money(r.ma5)}</td><td>${money(r.ma20)}<br><span class="label">${pct(r.ma20Slope)}</span></td><td>${money(r.ma60)}<br><span class="label">${pct(r.ma60Slope)}</span></td><td>${Number(r.trendScore||0).toFixed(2)}</td></tr>`).join("")}</tbody></table>`}
function renderPositions(rows){if(!rows.length){$("#positions").innerHTML="<p>No open paper positions.</p>";return}$("#positions").innerHTML=`<table><thead><tr><th>Coin</th><th>Entry</th><th>Price</th><th>MA20 Exit</th><th>MA60</th><th>To MA20</th><th>Value</th><th>Unrealized</th><th>Trades</th><th>Win Rate</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${r.instId}</strong></td><td>${money(r.avgEntry)}</td><td>${money(r.price)}</td><td>${money(r.ma20)}</td><td>${money(r.ma60)}</td><td class="${tone(r.distanceToMa20Pct)}">${pct(r.distanceToMa20Pct)}</td><td>${money(r.positionValue)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedPnlPct)}</td><td>${r.trades} / ${r.closedTrades}</td><td>${pct(r.winRate)}</td></tr>`).join("")}</tbody></table>`}
async function loadTrades(){const rows=await (await fetch("/api/crypto/micro/trades")).json();renderTrades(rows);}
function renderTrades(rows){if(!rows.length){$("#trades").innerHTML="<p>No entries or exits yet.</p>";return}$("#trades").innerHTML=`<table><thead><tr><th>Time</th><th>Coin</th><th>Side</th><th>Price</th><th>MA60</th><th>Amount</th><th>5m</th><th>15m</th><th>Vol x</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td>${r.inst_id}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${money(r.price)}</td><td>${money(r.ma60)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pct5)}">${pct(r.pct5)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td>${Number(r.volume_ratio||0).toFixed(2)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join("")}</tbody></table>`}
function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:6})}
function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`}
function tone(v){return Number(v)>=0?'good':'bad'}
</script></body></html>"""
