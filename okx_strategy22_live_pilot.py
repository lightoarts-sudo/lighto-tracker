#!/usr/bin/env python3
"""Small real-money OKX pilot for strategy22 slippage measurement.

Default mode is DRY-RUN. To place real orders, all of these are required:
  OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE
  OKX_STRATEGY22_PILOT_LIVE=1
  --i-understand-live-trading

The runner opens at most 10 strategy22 entries, each with 2 USDT margin and 5x
leverage by default, then exits them using the same strategy22 exit helper used
by the production paper/shadow loop. It records theoretical signal price,
bid/ask spread, actual fill price, and realized slippage to JSONL.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

OKX_BASE = os.environ.get("CRYPTO_OKX_BASE", "https://www.okx.com").rstrip("/")
CONFIG = None
fetch_market_tickers = None
fetch_okx_candles_by_inst = None
micro_top10_optimized_signal = None
micro_top10_optimized_should_exit = None
new_micro_state = None
shortlist_micro_tickers = None
to_micro_candles = None
update_micro_position_state = None


def load_crypto_bot_helpers() -> None:
    """Import crypto_bot lazily so pure helper tests do not need web/db deps."""
    global CONFIG, OKX_BASE, fetch_market_tickers, fetch_okx_candles_by_inst
    global micro_top10_optimized_signal, micro_top10_optimized_should_exit, new_micro_state
    global shortlist_micro_tickers, to_micro_candles, update_micro_position_state
    if CONFIG is not None:
        return
    import crypto_bot as bot

    CONFIG = bot.CONFIG
    OKX_BASE = bot.OKX_BASE
    fetch_market_tickers = bot.fetch_market_tickers
    fetch_okx_candles_by_inst = bot.fetch_okx_candles_by_inst
    micro_top10_optimized_signal = bot.micro_top10_optimized_signal
    micro_top10_optimized_should_exit = bot.micro_top10_optimized_should_exit
    new_micro_state = bot.new_micro_state
    shortlist_micro_tickers = bot.shortlist_micro_tickers
    to_micro_candles = bot.to_micro_candles
    update_micro_position_state = bot.update_micro_position_state


STRATEGY = "top10v1_rank5_chg3_10_sl1_trail09_t12"
STATE_PATH = Path(os.environ.get("OKX_STRATEGY22_PILOT_STATE", "data/okx_strategy22_live_pilot_state.json"))
LOG_PATH = Path(os.environ.get("OKX_STRATEGY22_PILOT_LOG", "data/okx_strategy22_live_pilot_log.jsonl"))
DEFAULT_KEY_FILE = Path(os.environ.get("OKX_KEY_FILE", r"C:\Users\fuful\OneDrive\Desktop\KEY\OKX API.txt"))
LOCK_PATH = Path(os.environ.get("OKX_STRATEGY22_PILOT_LOCK", "data/okx_strategy22_live_pilot.lock"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        # Windows/MSYS can raise SystemError/WinError 87 for os.kill(pid, 0).
        # Be conservative: treat unknown PID-probe failures as active so a
        # duplicate real-money runner cannot start and race into extra entries.
        return True


@contextmanager
def single_runner_lock():
    """Prevent two live pilot runners from racing into duplicate real entries."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "startedAt": utc_now_iso()}
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            current = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        except Exception:
            current = {"raw": LOCK_PATH.read_text(encoding="utf-8", errors="ignore") if LOCK_PATH.exists() else ""}
        pid = int(current.get("pid") or 0) if isinstance(current, dict) else 0
        if pid and not pid_is_running(pid):
            LOCK_PATH.unlink(missing_ok=True)
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            raise SystemExit(f"another okx_strategy22_live_pilot runner is already active: {current}")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    try:
        yield
    finally:
        try:
            current = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid():
                LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass


def okx_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sign_okx(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    prehash = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor((value / step) + 1e-12) * step


def decimals_for_step(step: float) -> int:
    text = f"{step:.16f}".rstrip("0").rstrip(".")
    return len(text.split(".", 1)[1]) if "." in text else 0


def format_size(value: float, step: float) -> str:
    decimals = decimals_for_step(step)
    return f"{value:.{decimals}f}" if decimals else str(int(value))


def calc_swap_order_size(notional_usdt: float, price: float, inst: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ct_val = float(inst.get("ctVal") or 0)
    lot_sz = float(inst.get("lotSz") or 0)
    min_sz = float(inst.get("minSz") or lot_sz or 0)
    if notional_usdt <= 0 or price <= 0 or ct_val <= 0 or lot_sz <= 0:
        raise ValueError(f"cannot calculate order size: notional={notional_usdt}, price={price}, inst={inst}")
    raw_sz = notional_usdt / (price * ct_val)
    sz = floor_to_step(raw_sz, lot_sz)
    if sz < min_sz:
        min_notional = min_sz * ct_val * price
        raise ValueError(
            f"2 USDT notional is below minimum for {inst.get('instId')}: minSz={min_sz}, approxMinNotional={min_notional:.6f}"
        )
    return format_size(sz, lot_sz), {"ctVal": ct_val, "lotSz": lot_sz, "minSz": min_sz, "rawSz": raw_sz, "roundedSz": sz}


def slippage_pct(side: str, theoretical_price: float, fill_price: float) -> float:
    if theoretical_price <= 0 or fill_price <= 0:
        return 0.0
    if side.lower() == "buy":
        return ((fill_price - theoretical_price) / theoretical_price) * 100
    return ((theoretical_price - fill_price) / theoretical_price) * 100


def format_price_for_okx(price: float) -> str:
    if price <= 0:
        raise ValueError(f"OKX price must be positive: {price}")
    return f"{price:.12f}".rstrip("0").rstrip(".")


def calc_long_stop_loss_price(entry_price: float, stop_pct: float) -> float:
    if entry_price <= 0:
        raise ValueError(f"entry price must be positive: {entry_price}")
    if stop_pct <= 0 or stop_pct >= 100:
        raise ValueError(f"stop loss pct must be between 0 and 100: {stop_pct}")
    return entry_price * (1 - stop_pct / 100.0)


def build_long_stop_loss_algo_payload(
    inst_id: str,
    td_mode: str,
    sz: str,
    stop_price: float,
    trigger_px_type: str = "last",
) -> dict[str, Any]:
    """Build an OKX exchange-native stop-loss algo order for a long swap position.

    OKX uses `slOrdPx=-1` to place a market order when the stop is triggered.
    The pilot runs in net mode, so a long hard stop is a sell reduce-only algo.
    """
    return {
        "instId": inst_id,
        "tdMode": td_mode,
        "side": "sell",
        "ordType": "conditional",
        "sz": sz,
        "slTriggerPx": format_price_for_okx(stop_price),
        "slOrdPx": "-1",
        "slTriggerPxType": trigger_px_type,
        "reduceOnly": "true",
    }


def is_no_position_reduce_error(exc: Exception) -> bool:
    """OKX 51169 means local state says open, but exchange has no reducible long."""
    text = str(exc)
    return "51169" in text and "don't have any positions" in text


def okx_position_contract_size(position_rows: list[dict[str, Any]], inst_id: str) -> float:
    """Return the absolute OKX net position size for an instrument, or 0 if flat."""
    for row in position_rows:
        if row.get("instId") != inst_id:
            continue
        try:
            return abs(float(row.get("pos") or 0))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def parse_okx_key_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    aliases = {
        "apikey": "api_key",
        "api_key": "api_key",
        "api key": "api_key",
        "okx_api_key": "api_key",
        "secretkey": "api_secret",
        "secret_key": "api_secret",
        "secret key": "api_secret",
        "okx_api_secret": "api_secret",
        "passphrase": "passphrase",
        "api_passphrase": "passphrase",
        "okx_api_passphrase": "passphrase",
        "交易密碼": "passphrase",
        "api密碼": "passphrase",
        "密碼": "passphrase",
    }
    out: dict[str, str] = {}
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    unlabelled: list[str] = []
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            unlabelled.append(line.strip().strip('"'))
            continue
        normal = key.strip().lower().replace("-", "_")
        mapped = aliases.get(normal)
        if mapped:
            out[mapped] = value.strip().strip('"')
    # Support a simple 3-line file: api_key, api_secret, passphrase.
    if unlabelled:
        for mapped, value in zip(["api_key", "api_secret", "passphrase"], unlabelled):
            out.setdefault(mapped, value)
    return out


@dataclass
class OkxCredentials:
    api_key: str
    api_secret: str
    passphrase: str
    simulated: bool = False

    @classmethod
    def from_env(cls) -> "OkxCredentials":
        file_creds = parse_okx_key_file(DEFAULT_KEY_FILE)
        api_key = os.environ.get("OKX_API_KEY") or file_creds.get("api_key", "")
        api_secret = os.environ.get("OKX_API_SECRET") or file_creds.get("api_secret", "")
        passphrase = (
            os.environ.get("OKX_API_PASSPHRASE")
            or os.environ.get("OKX_PASSPHRASE")
            or file_creds.get("passphrase", "")
        )
        missing = [name for name, value in [("OKX_API_KEY", api_key), ("OKX_API_SECRET", api_secret), ("OKX_API_PASSPHRASE", passphrase)] if not value]
        if missing:
            hint = f"; checked key file {DEFAULT_KEY_FILE}" if DEFAULT_KEY_FILE.exists() else f"; key file not found: {DEFAULT_KEY_FILE}"
            raise RuntimeError(f"missing OKX credentials: {', '.join(missing)}{hint}")
        simulated = os.environ.get("OKX_SIMULATED", "0") in {"1", "true", "TRUE", "yes", "YES"}
        return cls(api_key=api_key, api_secret=api_secret, passphrase=passphrase, simulated=simulated)


class OkxPrivateClient:
    def __init__(self, client: httpx.AsyncClient, creds: OkxCredentials):
        self.client = client
        self.creds = creds

    async def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")) if payload else ""
        ts = okx_timestamp()
        headers = {
            "OK-ACCESS-KEY": self.creds.api_key,
            "OK-ACCESS-SIGN": sign_okx(ts, method, path, body, self.creds.api_secret),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.creds.passphrase,
            "Content-Type": "application/json",
        }
        if self.creds.simulated:
            headers["x-simulated-trading"] = "1"
        resp = await self.client.request(method, f"{OKX_BASE}{path}", headers=headers, content=body or None)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            raise RuntimeError(f"OKX private API error {method} {path}: {data}")
        return data

    async def set_leverage(self, inst_id: str, lever: float, mgn_mode: str) -> dict[str, Any]:
        return await self.request("POST", "/api/v5/account/set-leverage", {"instId": inst_id, "lever": str(lever), "mgnMode": mgn_mode})

    async def market_order(self, inst_id: str, side: str, sz: str, td_mode: str, reduce_only: bool = False) -> dict[str, Any]:
        payload = {"instId": inst_id, "tdMode": td_mode, "side": side, "ordType": "market", "sz": sz}
        if reduce_only:
            payload["reduceOnly"] = "true"
        return await self.request("POST", "/api/v5/trade/order", payload)

    async def place_long_stop_loss(self, inst_id: str, sz: str, td_mode: str, stop_price: float) -> dict[str, Any]:
        payload = build_long_stop_loss_algo_payload(inst_id, td_mode, sz, stop_price)
        return await self.request("POST", "/api/v5/trade/order-algo", payload)

    async def order_details(self, inst_id: str, ord_id: str) -> dict[str, Any]:
        path = f"/api/v5/trade/order?instId={inst_id}&ordId={ord_id}"
        return await self.request("GET", path)

    async def positions(self, inst_id: str | None = None) -> dict[str, Any]:
        path = "/api/v5/account/positions?instType=SWAP"
        if inst_id:
            path = f"/api/v5/account/positions?instId={inst_id}"
        return await self.request("GET", path)


class Pilot:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.state = self.load_state()
        self.instruments: dict[str, dict[str, Any]] = {}

    def load_state(self) -> dict[str, Any]:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {"startedAt": utc_now_iso(), "entriesPlaced": 0, "positions": {}, "completed": False}

    def save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def log(self, event: str, **payload: Any) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": utc_now_iso(), "event": event, **payload}
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)

    async def reconcile_exchange_position(self, okx: OkxPrivateClient | None, inst_id: str, position: dict[str, Any]) -> bool:
        """Check OKX before local K-line exit management.

        Returns True when the local position still exists on OKX. Returns False
        after removing stale local state, e.g. an exchange-native hard stop has
        already closed the position between polling cycles.
        """
        if not self.args.live:
            return True
        assert okx is not None
        data = await okx.positions(inst_id)
        exchange_sz = okx_position_contract_size(data.get("data", []), inst_id)
        state = position.get("state", {})
        local_sz = float(state.get("contractSize") or 0)
        if exchange_sz <= 0:
            self.state["positions"].pop(inst_id, None)
            self.save_state()
            self.log(
                "EXCHANGE_POSITION_CLOSED",
                instId=inst_id,
                localSz=local_sz,
                hardStopAlgoId=position.get("hardStopAlgoId") or state.get("hardStopAlgoId"),
                note="OKX reports no open position; likely exchange-native hard stop or manual close filled between runner polls",
            )
            return False
        if local_sz > 0 and abs(exchange_sz - local_sz) > max(1e-9, local_sz * 0.000001):
            lot_sz = float(position.get("inst", {}).get("lotSz") or 1)
            ct_val = float(position.get("inst", {}).get("ctVal") or 0)
            state["contractSize"] = format_size(exchange_sz, lot_sz)
            if ct_val > 0:
                state["assetQty"] = exchange_sz * ct_val
            position["state"] = state
            self.state["positions"][inst_id] = position
            self.save_state()
            self.log("EXCHANGE_POSITION_SIZE_SYNC", instId=inst_id, localSz=local_sz, exchangeSz=exchange_sz)
        return True

    async def load_instruments(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"{OKX_BASE}/api/v5/public/instruments", params={"instType": "SWAP"})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            raise RuntimeError(f"OKX instruments error: {data}")
        self.instruments = {row["instId"]: row for row in data.get("data", [])}

    async def scan_top10_strategy(self, client: httpx.AsyncClient) -> list[tuple[str, dict[str, Any], float]]:
        tickers = await fetch_market_tickers(client, CONFIG["microInstType"])
        shortlist = shortlist_micro_tickers(tickers)
        scanned = []
        for ticker in shortlist:
            inst_id = ticker["instId"]
            raw = await fetch_okx_candles_by_inst(client, inst_id, CONFIG["microBaseInterval"], 240)
            candles = to_micro_candles(raw)
            if len(candles) < 72:
                continue
            base_signal = __import__("crypto_bot").micro_trend_signal(ticker, candles)
            scanned.append((base_signal.get("pct1h", 0), inst_id, ticker, candles, candles[-1]["close"]))
            await asyncio.sleep(self.args.scan_pause)
        scanned.sort(reverse=True, key=lambda row: row[0])
        signals = []
        for rank, (change_1h, inst_id, ticker, candles, price) in enumerate(scanned[:10], start=1):
            signal = micro_top10_optimized_signal(ticker, candles, STRATEGY, rank_1h=rank, collector_change_1h_pct=change_1h)
            if signal.get("buy"):
                signals.append((inst_id, signal, price))
        return signals

    async def poll_fill_price(self, okx: OkxPrivateClient, inst_id: str, ord_id: str) -> float:
        last_data: dict[str, Any] | None = None
        for _ in range(10):
            data = await okx.order_details(inst_id, ord_id)
            last_data = data
            rows = data.get("data", [])
            if rows:
                avg_px = float(rows[0].get("avgPx") or 0)
                if avg_px > 0:
                    return avg_px
            await asyncio.sleep(0.7)
        raise RuntimeError(f"order did not report avgPx: {last_data}")

    async def open_position(self, okx: OkxPrivateClient | None, inst_id: str, signal: dict[str, Any], price: float) -> None:
        if self.state["entriesPlaced"] >= self.args.max_entries:
            return
        if inst_id in self.state["positions"]:
            return
        inst = self.instruments.get(inst_id)
        if not inst:
            self.log("skip_no_instrument", instId=inst_id)
            return
        try:
            sz, sizing = calc_swap_order_size(self.args.margin_usdt * self.args.leverage, price, inst)
        except Exception as exc:
            self.log("skip_sizing", instId=inst_id, error=str(exc), signalPrice=price)
            return
        theoretical = price
        fill_price = float(signal.get("bestAsk") or theoretical)
        order_id = None
        hard_stop_price = calc_long_stop_loss_price(fill_price, self.args.hard_stop_pct)
        hard_stop_algo_id = None
        if self.args.live:
            assert okx is not None
            await okx.set_leverage(inst_id, self.args.leverage, self.args.margin_mode)
            data = await okx.market_order(inst_id, "buy", sz, self.args.margin_mode)
            order_id = data["data"][0]["ordId"]
            fill_price = await self.poll_fill_price(okx, inst_id, order_id)
            hard_stop_price = calc_long_stop_loss_price(fill_price, self.args.hard_stop_pct)
            try:
                stop_data = await okx.place_long_stop_loss(inst_id, sz, self.args.margin_mode, hard_stop_price)
                hard_stop_algo_id = stop_data.get("data", [{}])[0].get("algoId")
            except Exception as exc:
                self.log(
                    "HARD_STOP_FAILED_EMERGENCY_CLOSE",
                    instId=inst_id,
                    openOrderId=order_id,
                    sz=sz,
                    fillPrice=fill_price,
                    hardStopPct=self.args.hard_stop_pct,
                    hardStopPrice=hard_stop_price,
                    error=str(exc),
                )
                await okx.market_order(inst_id, "sell", sz, self.args.margin_mode, reduce_only=True)
                raise RuntimeError(f"opened {inst_id} but failed to place OKX hard stop; emergency close sent") from exc
        state = new_micro_state()
        notional = float(sz) * float(inst["ctVal"]) * fill_price
        qty_base = notional / fill_price
        state.update({
            "assetQty": qty_base,
            "contractSize": sz,
            "avgEntry": fill_price,
            "margin": self.args.margin_usdt,
            "leverage": self.args.leverage,
            "notional": notional,
            "entryTime": signal["time"],
            "entryReason": signal["reason"],
            "peakPrice": fill_price,
            "belowMa60Count": 0,
            "tp1Taken": False,
            "tp2Taken": False,
            "breakevenStopPrice": 0,
            "hardStopLossPct": self.args.hard_stop_pct,
            "hardStopLossPrice": hard_stop_price,
            "hardStopAlgoId": hard_stop_algo_id,
            "trades": 1,
        })
        self.state["positions"][inst_id] = {
            "state": state,
            "signal": signal,
            "inst": inst,
            "openedAt": utc_now_iso(),
            "openOrderId": order_id,
            "hardStopAlgoId": hard_stop_algo_id,
            "strategy": STRATEGY,
        }
        self.state["entriesPlaced"] += 1
        self.save_state()
        self.log(
            "BUY" if self.args.live else "DRY_RUN_BUY",
            instId=inst_id,
            orderId=order_id,
            sz=sz,
            sizing=sizing,
            theoreticalPrice=theoretical,
            fillPrice=fill_price,
            slippagePct=slippage_pct("buy", theoretical, fill_price),
            hardStopPct=self.args.hard_stop_pct,
            hardStopPrice=hard_stop_price,
            hardStopAlgoId=hard_stop_algo_id,
            spreadPct=signal.get("spreadPct"),
            buySlippagePct=signal.get("buySlippagePct"),
            signal={k: signal.get(k) for k in ("pct1h", "pct2h", "pct3h", "pct15", "volumeRatio", "reason")},
        )

    async def close_position(self, okx: OkxPrivateClient | None, inst_id: str, position: dict[str, Any], signal: dict[str, Any], price: float) -> None:
        state = position["state"]
        inst = position["inst"]
        fraction = min(1.0, max(0.0, float(signal.get("exitFraction", 1.0))))
        current_sz = float(state["contractSize"])
        lot_sz = float(inst.get("lotSz") or 1)
        sell_sz_value = floor_to_step(current_sz * fraction, lot_sz)
        if sell_sz_value <= 0:
            return
        sell_sz = format_size(sell_sz_value, lot_sz)
        theoretical = signal.get("exitPrice") or price
        fill_price = float(signal.get("bestBid") or theoretical)
        order_id = None
        if self.args.live:
            assert okx is not None
            try:
                data = await okx.market_order(inst_id, "sell", sell_sz, self.args.margin_mode, reduce_only=True)
            except RuntimeError as exc:
                if is_no_position_reduce_error(exc):
                    self.state["positions"].pop(inst_id, None)
                    self.save_state()
                    self.log(
                        "POSITION_MISSING_ON_CLOSE",
                        instId=inst_id,
                        sz=sell_sz,
                        reason=signal.get("exitReason"),
                        error=str(exc),
                    )
                    return
                raise
            order_id = data["data"][0]["ordId"]
            fill_price = await self.poll_fill_price(okx, inst_id, order_id)
        realized_pnl = (fill_price - state["avgEntry"]) * (sell_sz_value * float(inst["ctVal"]))
        remaining_sz = max(0.0, current_sz - sell_sz_value)
        full_exit = remaining_sz <= current_sz * 0.000001
        state["contractSize"] = format_size(remaining_sz, lot_sz) if not full_exit else "0"
        state["assetQty"] = 0.0 if full_exit else remaining_sz * float(inst["ctVal"])
        state["realizedPnl"] = state.get("realizedPnl", 0.0) + realized_pnl
        state["trades"] = state.get("trades", 0) + 1
        if full_exit:
            self.state["positions"].pop(inst_id, None)
        else:
            position["state"] = state
            self.state["positions"][inst_id] = position
        self.save_state()
        self.log(
            "SELL" if self.args.live else "DRY_RUN_SELL",
            instId=inst_id,
            orderId=order_id,
            sz=sell_sz,
            fraction=fraction,
            reason=signal.get("exitReason"),
            theoreticalPrice=theoretical,
            fillPrice=fill_price,
            slippagePct=slippage_pct("sell", theoretical, fill_price),
            realizedPnl=realized_pnl,
            fullExit=full_exit,
        )

    async def run(self) -> None:
        load_crypto_bot_helpers()
        CONFIG["microMarginUSDT"] = self.args.margin_usdt
        CONFIG["microLeverage"] = self.args.leverage
        creds = OkxCredentials.from_env() if self.args.live else None
        async with httpx.AsyncClient(timeout=25) as client:
            okx = OkxPrivateClient(client, creds) if creds else None
            await self.load_instruments(client)
            self.log(
                "start",
                live=self.args.live,
                maxEntries=self.args.max_entries,
                marginUSDT=self.args.margin_usdt,
                leverage=self.args.leverage,
                topN=10,
                strategy=STRATEGY,
                hardStopPct=self.args.hard_stop_pct,
            )
            while True:
                # Manage open positions first.
                tickers = {t["instId"]: t for t in await fetch_market_tickers(client, CONFIG["microInstType"])}
                for inst_id, position in list(self.state.get("positions", {}).items()):
                    if not await self.reconcile_exchange_position(okx, inst_id, position):
                        continue
                    ticker = tickers.get(inst_id)
                    if not ticker:
                        continue
                    raw = await fetch_okx_candles_by_inst(client, inst_id, CONFIG["microBaseInterval"], 240)
                    candles = to_micro_candles(raw)
                    signal = micro_top10_optimized_signal(ticker, candles, position.get("strategy", STRATEGY), rank_1h=None, collector_change_1h_pct=None)
                    price = candles[-1]["close"]
                    update_micro_position_state(position["state"], price, signal)
                    if micro_top10_optimized_should_exit(signal, position["state"], price, position.get("strategy", STRATEGY)):
                        await self.close_position(okx, inst_id, position, signal, signal.get("exitPrice", price))
                    else:
                        position["state"] = position["state"]
                        position["signal"] = signal
                        self.state["positions"][inst_id] = position
                        self.save_state()

                if self.state["entriesPlaced"] < self.args.max_entries:
                    signals = await self.scan_top10_strategy(client)
                    for inst_id, signal, price in signals:
                        if self.state["entriesPlaced"] >= self.args.max_entries:
                            break
                        await self.open_position(okx, inst_id, signal, price)
                if self.state["entriesPlaced"] >= self.args.max_entries and not self.state.get("positions"):
                    self.state["completed"] = True
                    self.save_state()
                    self.log("completed", entriesPlaced=self.state["entriesPlaced"])
                    return
                if self.args.once:
                    self.log("once_done", entriesPlaced=self.state["entriesPlaced"], openPositions=len(self.state.get("positions", {})))
                    return
                await asyncio.sleep(self.args.poll_seconds)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="strategy22 OKX live slippage pilot")
    p.add_argument("--max-entries", type=int, default=int(os.environ.get("OKX_STRATEGY22_PILOT_MAX_ENTRIES", "10")))
    p.add_argument("--margin-usdt", type=float, default=float(os.environ.get("OKX_STRATEGY22_PILOT_MARGIN_USDT", "2")))
    p.add_argument("--leverage", type=float, default=float(os.environ.get("OKX_STRATEGY22_PILOT_LEVERAGE", "5")))
    p.add_argument("--margin-mode", default=os.environ.get("OKX_STRATEGY22_PILOT_MARGIN_MODE", "isolated"))
    p.add_argument("--top-n", type=int, default=int(os.environ.get("OKX_STRATEGY22_PILOT_TOP_N", "20")))
    p.add_argument("--poll-seconds", type=int, default=int(os.environ.get("OKX_STRATEGY22_PILOT_POLL_SECONDS", "300")))
    p.add_argument("--scan-pause", type=float, default=float(os.environ.get("OKX_STRATEGY22_PILOT_SCAN_PAUSE", "0.08")))
    p.add_argument("--hard-stop-pct", type=float, default=float(os.environ.get("OKX_STRATEGY22_PILOT_HARD_STOP_PCT", "1.0")), help="exchange-native hard stop loss percentage placed immediately after each live entry")
    p.add_argument("--once", action="store_true", help="run one scan/manage pass and exit")
    p.add_argument("--i-understand-live-trading", action="store_true", help="required together with OKX_STRATEGY22_PILOT_LIVE=1 to place real orders")
    args = p.parse_args()
    if args.hard_stop_pct <= 0 or args.hard_stop_pct >= 100:
        raise SystemExit("--hard-stop-pct must be greater than 0 and less than 100")
    live_env = os.environ.get("OKX_STRATEGY22_PILOT_LIVE", "0") in {"1", "true", "TRUE", "yes", "YES"}
    args.live = bool(live_env and args.i_understand_live_trading)
    if live_env and not args.i_understand_live_trading:
        raise SystemExit("OKX_STRATEGY22_PILOT_LIVE=1 set, but --i-understand-live-trading was not provided; refusing to place real orders")
    return args


if __name__ == "__main__":
    with single_runner_lock():
        asyncio.run(Pilot(parse_args()).run())
