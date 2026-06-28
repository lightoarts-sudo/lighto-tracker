#!/usr/bin/env python3
"""Focused production backtest for a new optimizer candidate."""
from __future__ import annotations
import json, math, sqlite3, types, sys
from collections import Counter

# Stub asyncpg/fastapi before crypto_bot import
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
if "fastapi" not in sys.modules:
    class _DummyFastAPI:
        def __init__(self, *args, **kwargs): pass
        def get(self, *a, **k): return lambda fn: fn
        def post(self, *a, **k): return lambda fn: fn
        def on_event(self, *a, **k): return lambda fn: fn
    def _Query(default=None, *a, **k): return default
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_DummyFastAPI, Query=_Query)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)

import crypto_bot as cb

ROUND_TRIP = 0.16

CANDIDATE = {
    "entry": {
        "name": "delay3_rank3_chg3-10_green_vol_dur8-50",
        "delay_bars": 3,
        "max_entry_rank": 3,
        "min_entry_change": 3,
        "max_entry_change": 10,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "min_vol_ratio": 1.0,
        "reclaim_entry_price": False,
        "min_session_bars": 8,
        "max_session_bars": 50,
    },
    "exit": {
        "name": "sl0.8_be0.6_trail0.9x0.4_t8",
        "sl_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trail_start_pct": 0.9,
        "trail_giveback_pct": 0.4,
        "time_stop_bars": 8,
    },
}

def main():
    db_path = "data/okx_micro_5m_tracking.sqlite"
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    # Inject candidate into registry for signal helpers
    sid = "auto_new_4h_d3_r3_chg3-10_green_vol_dur8-50_sl0.8_be0.6_tr0.9x0.4_t8"
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[sid] = {
        "version": "auto_new_4h",
        "entry_delay_bars": 3,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "min_volume_ratio": 1.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 8,
    }

    # Load sources from rankings (point-in-time 1H Top10 universe)
    runs = {}
    for row in con.execute(
        """
        select r.id as run_id, r.captured_at, k.rank_1h, k.inst_id, k.base_ccy,
               k.last, k.change_1h_pct, k.quote_vol_24h, k.last_ts_ms
        from top10_1h_training_runs r
        join top10_1h_training_rankings k on k.run_id = r.id
        order by r.id, k.rank_1h
        """
    ):
        runs.setdefault(int(row["run_id"]), []).append(row)

    positions = {}
    trades = []
    skipped = 0

    def load_candles(inst_id, ts_ms, limit=240):
        rows = list(con.execute(
            "select ts_ms, open, high, low, close, vol_ccy, vol from candles_5m where inst_id=? and ts_ms<=? order by ts_ms desc limit ?",
            (inst_id, ts_ms, limit),
        ))
        rows.reverse()
        return [
            {"time": int(r["ts_ms"]), "closeTime": int(r["ts_ms"]),
             "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]),
             "volume": float(r["vol_ccy"] or r["vol"] or 0.0)}
            for r in rows
        ]

    def pct(a, b):
        return (a / b - 1.0) * 100.0 if b else 0.0

    def should_exit(signal, state, price):
        return cb.micro_top10_optimized_should_exit(signal, state, price, sid)

    for run_id in sorted(runs):
        rows = runs[run_id]
        ts_ms = int(rows[0]["last_ts_ms"] or 0)
        universe = []
        for r in rows:
            inst = r["inst_id"]
            candles = load_candles(inst, ts_ms)
            if len(candles) < 61:
                skipped += 1
                continue
            ticker = {"instId": inst, "_pct24": 0.0, "_quoteVol": float(r["quote_vol_24h"] or 0.0), "bidPx": None, "askPx": None}
            sources[inst] = {"ticker": ticker, "candles": candles, "rank_1h": int(r["rank_1h"])}

        # Carry open positions
        for inst in list(positions.keys()):
            if inst not in sources:
                continue
            state = positions[inst]
            candles = sources[inst]["candles"]
            price = candles[-1]["close"]
            signal = cb.micro_trend_signal(sources[inst]["ticker"], candles)
            signal["rank1h"] = sources[inst]["rank_1h"]
            signal["collectorChange1hPct"] = float(next(r["change_1h_pct"] for r in rows if r["inst_id"] == inst) or 0.0)
            cb.update_micro_position_state(state, price, signal)
            if cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[sid].get("session_end_exit") and state.get("sessionEnd", 0) == 0:
                state["sessionEnd"] = 1
            if should_exit(signal, state, price):
                ret = pct(price, state["avgEntry"]) * 100.0
                trades.append({
                    "inst_id": inst,
                    "gross_return_pct": ret,
                    "net_return_pct": ret - ROUND_TRIP,
                    "exit_reason": signal.get("exitReason", "exit"),
                })
                del positions[inst]

        # Entry logic (simplified: use micro_top10_optimized_signal)
        for r in rows:
            inst = r["inst_id"]
            if inst in positions:
                continue
            candles = load_candles(inst, ts_ms)
            if len(candles) < 61:
                continue
            ticker = {"instId": inst, "_pct24": 0.0, "_quoteVol": float(r["quote_vol_24h"] or 0.0), "bidPx": None, "askPx": None}
            sig = cb.micro_top10_optimized_signal(ticker, candles, sid, rank_1h=int(r["rank_1h"]), collector_change_1h_pct=float(r["change_1h_pct"] or 0.0), session_age_bars=0)
            if sig.get("buy"):
                price = candles[-1]["close"]
                state = cb.new_micro_state()
                state.update({"assetQty": 1.0, "avgEntry": price, "margin": 1.0, "notional": price, "peakPrice": price, "entryTime": candles[-1]["time"], "trades": 1})
                positions[inst] = state

    # Close remaining positions at end using last available price proxy
    for inst, state in list(positions.items()):
        candles = load_candles(inst, con.execute("select max(ts_ms) from candles_5m where inst_id=?", (inst,)).fetchone()[0] or 0, limit=1)
        price = candles[-1]["close"] if candles else state["avgEntry"]
        ret = pct(price, state["avgEntry"]) * 100.0
        trades.append({
            "inst_id": inst,
            "gross_return_pct": ret,
            "net_return_pct": ret - ROUND_TRIP,
            "exit_reason": "session_end",
        })

    net = [t["net_return_pct"] for t in trades]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    print(json.dumps({
        "strategy": sid,
        "closed_trades": len(trades),
        "win_rate": len(wins)/len(trades)*100 if trades else 0,
        "net_avg_return": sum(net)/len(net) if net else 0,
        "profit_factor": pf,
        "max_loss": min(net) if net else 0,
        "exit_reasons": dict(Counter(t["exit_reason"] for t in trades)),
        "skipped": skipped,
    }, indent=2))

    con.close()

if __name__ == "__main__":
    main()
