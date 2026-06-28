#!/usr/bin/env python3
"""Local backtest of strategies from strategy_pool.json against the local SQLite,
then output top3 by net_avg_return and profit_factor.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from statistics import median
from collections import Counter

# --- Stubs so tmp_top10_training_optimizer can be imported standalone ---
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
if "fastapi" not in sys.modules:
    class _FA:
        def __init__(self, *a, **kw): pass
        def get(self, *a, **kw): return lambda fn: fn
        def post(self, *a, **kw): return lambda fn: fn
        def on_event(self, *a, **kw): return lambda fn: fn
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_FA, Query=lambda *a, **kw: None)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)

from tmp_top10_training_optimizer import (
    EntryRule, ExitRule, load_sessions, entry_ok, simulate_exit, ROUND_TRIP_COST_PCT,
    max_drawdown_proxy,
)


DB_PATH = Path("data/okx_micro_5m_tracking.sqlite")
POOL_PATH = Path("data/strategy_pool.json")
TOP_N = 3


def build_entry_rule(raw: dict) -> EntryRule:
    entry = raw.get("entry") or {}
    return EntryRule(
        name=entry.get("name", ""),
        delay_bars=int(entry.get("delay_bars") or 0),
        max_entry_rank=int(entry.get("max_entry_rank") or 99),
        min_entry_change=float(entry.get("min_entry_change") or 0),
        max_entry_change=float(entry.get("max_entry_change") or 100),
        require_green_confirm=bool(entry.get("require_green_confirm") or False),
        max_upper_wick_pct=entry.get("max_upper_wick_pct"),
        min_vol_ratio=entry.get("min_vol_ratio"),
        reclaim_entry_price=bool(entry.get("reclaim_entry_price") or False),
        min_atr_proxy=entry.get("min_atr_proxy"),
        max_atr_proxy=entry.get("max_atr_proxy"),
        allowed_hours=tuple(entry.get("allowed_hours")) if entry.get("allowed_hours") else None,
        min_session_bars=entry.get("min_session_bars"),
        max_session_bars=entry.get("max_session_bars"),
        min_rank_momentum=entry.get("min_rank_momentum"),
    )


def build_exit_rule(raw: dict) -> ExitRule:
    exit_ = raw.get("exit") or {}
    return ExitRule(
        name=exit_.get("name", ""),
        sl_pct=float(exit_.get("sl_pct") or 1.0),
        tp_pct=float(exit_.get("tp_pct")) if exit_.get("tp_pct") is not None else None,
        time_stop_bars=int(exit_.get("time_stop_bars") or 12),
        breakeven_after_pct=float(exit_.get("breakeven_after_pct")) if exit_.get("breakeven_after_pct") is not None else None,
        trail_start_pct=float(exit_.get("trail_start_pct")) if exit_.get("trail_start_pct") is not None else None,
        trail_giveback_pct=float(exit_.get("trail_giveback_pct")) if exit_.get("trail_giveback_pct") is not None else None,
    )


def score_candidate(cid: str, er: EntryRule, xr: ExitRule, sessions: dict) -> dict | None:
    trades = []
    for sid, rows in sessions.items():
        ok, idx, price, _ = entry_ok(rows, er)
        if not ok or price <= 0:
            continue
        ret, reason, bars = simulate_exit(rows, idx, price, xr)
        if reason == "no_exit_bar":
            continue
        trades.append({
            "session_id": sid,
            "gross_return_pct": ret,
            "exit_reason": reason,
            "bars_held": bars,
        })

    if not trades:
        return None

    gross = [t["gross_return_pct"] for t in trades]
    net = [r - ROUND_TRIP_COST_PCT for r in gross]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    gp = sum(wins)
    gl = -sum(losses) if losses else 0.0
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)

    return {
        "id": cid,
        "entry_name": er.name,
        "exit_name": xr.name,
        "trades": len(trades),
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "avg_return": sum(gross) / len(gross) if gross else 0.0,
        "median_return": median(gross) if gross else 0.0,
        "net_avg_return": sum(net) / len(net) if net else 0.0,
        "profit_factor": pf,
        "max_loss": min(net) if net else 0.0,
        "max_drawdown_proxy": max_drawdown_proxy(net),
        "exit_reason_counts": dict(Counter(t["exit_reason"] for t in trades)),
    }


def main():
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    candidates = pool.get("candidates", [])
    stats, sessions = load_sessions(str(DB_PATH))
    print(f"DB stats: {stats['dataset_rows']} rows, {stats['sessions']} sessions "
          f"({stats['closed_sessions']} closed) from {stats['min_ts_iso']} to {stats['max_ts_iso']}")
    print(f"Candidates to backtest: {len(candidates)}\n")

    results = []
    for c in candidates:
        cid = c.get("id", "")
        try:
            er = build_entry_rule(c)
            xr = build_exit_rule(c)
            res = score_candidate(cid, er, xr, sessions)
            if res:
                results.append((cid, res))
                print(f"OK: {cid} => trades={res['trades']} wr={res['win_rate']:.1f}% "
                      f"net={res['net_avg_return']:.3f}% pf={res['profit_factor']:.2f}")
            else:
                print(f"SKIP: {cid} => no trades")
        except Exception as exc:  # noqa
            print(f"ERR: {cid} => {exc}")

    if not results:
        print("\nNo candidate produced trades.")
        return

    # Rank: net_avg_return desc, then profit_factor desc
    results.sort(key=lambda x: (x[1]["net_avg_return"], x[1]["profit_factor"]), reverse=True)

    print("\n" + "=" * 70)
    print(f"TOP{TOP_N} strategies by net_avg_return:")
    print("=" * 70)
    for rank, (cid, r) in enumerate(results[:TOP_N], start=1):
        print(f"\n#{rank}  {cid}")
        print(f"  Entry : {r['entry_name']}")
        print(f"  Exit  : {r['exit_name']}")
        print(f"  Trades: {r['closed_trades']}   Win Rate: {r['win_rate']:.1f}%")
        print(f"  Net Avg Return: {r['net_avg_return']:.4f}%   PF: {r['profit_factor']:.3f}")
        print(f"  Max Loss: {r['max_loss']:.3f}%   Max DD proxy: {r['max_drawdown_proxy']:.3f}%")
        print(f"  Exit reasons: {r['exit_reason_counts']}")

    print("\nFull ranking:")
    print(f"{'CID':<45} {'Trades':>6} {'WR':>6} {'Net%':>9} {'PF':>7}")
    print("-" * 75)
    for cid, r in results:
        print(f"{cid:<45} {r['closed_trades']:>6} {r['win_rate']:>5.1f}% "
              f"{r['net_avg_return']:>8.3f}% {r['profit_factor']:>7.2f}")


if __name__ == "__main__":
    main()
