#!/usr/bin/env python3
"""Comprehensive local strategy scanner on top3-only DB.
- Input: data/okx_micro_5m_tracking.sqlite (top3-entry sessions, ~23 days)
- Output: all strategy configs ranked by win_rate, then net_avg_return
- Uses same backtest engine as tmp_top10_training_optimizer.py

用法:
  python local_strategy_scanner.py [--min-trades 30] [--top 20]
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Optional

# --- stubs for standalone ---
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
    max_drawdown_proxy, pct,
)

DB_PATH = Path("data/okx_micro_5m_tracking.sqlite")


# ---------------------------------------------------------------------------
# Parameter grid: expand beyond the optimizer's fixed rules
# ---------------------------------------------------------------------------

def build_entry_grid() -> list[EntryRule]:
    rules: list[EntryRule] = []
    for delay in [1, 2, 3]:
        for max_rank in [1, 2, 3, 5]:
            for lo, hi in [(1, 5), (2, 8), (3, 10), (5, 15)]:
                # base: green confirm, wick=1.2%, vol=1.0
                rules.append(EntryRule(
                    name=f"d{delay}_r{max_rank}_chg{lo}-{hi}_gv",
                    delay_bars=delay, max_entry_rank=max_rank,
                    min_entry_change=lo, max_entry_change=hi,
                    require_green_confirm=True, max_upper_wick_pct=1.2,
                    min_vol_ratio=1.0, reclaim_entry_price=False,
                    allowed_hours=None, min_session_bars=None, max_session_bars=None,
                    min_rank_momentum=None,
                ))
                # stricter: wick=0.8%, vol=2.0, reclaim=True
                rules.append(EntryRule(
                    name=f"d{delay}_r{max_rank}_chg{lo}-{hi}_gv_strict",
                    delay_bars=delay, max_entry_rank=max_rank,
                    min_entry_change=lo, max_entry_change=hi,
                    require_green_confirm=True, max_upper_wick_pct=0.8,
                    min_vol_ratio=2.0, reclaim_entry_price=True,
                    allowed_hours=None, min_session_bars=None, max_session_bars=None,
                    min_rank_momentum=None,
                ))
                # ATR proxy variants
                for atr_lo, atr_hi in [(2, 15), (5, 20), (None, None)]:
                    if atr_lo is None:
                        name = f"d{delay}_r{max_rank}_chg{lo}-{hi}_gv"
                    else:
                        name = f"d{delay}_r{max_rank}_chg{lo}-{hi}_gv_atr{atr_lo}-{atr_hi}"
                    rules.append(EntryRule(
                        name=name,
                        delay_bars=delay, max_entry_rank=max_rank,
                        min_entry_change=lo, max_entry_change=hi,
                        require_green_confirm=True, max_upper_wick_pct=1.2,
                        min_vol_ratio=1.0, reclaim_entry_price=False,
                        min_atr_proxy=atr_lo, max_atr_proxy=atr_hi,
                        allowed_hours=None, min_session_bars=None, max_session_bars=None,
                        min_rank_momentum=None,
                    ))
                # Duration variants
                for dlo, dhi in [(6, 60), (8, 50), (10, 40)]:
                    rules.append(EntryRule(
                        name=f"d{delay}_r{max_rank}_chg{lo}-{hi}_gv_dur{dlo}-{dhi}",
                        delay_bars=delay, max_entry_rank=max_rank,
                        min_entry_change=lo, max_entry_change=hi,
                        require_green_confirm=True, max_upper_wick_pct=1.2,
                        min_vol_ratio=1.0, reclaim_entry_price=False,
                        min_session_bars=dlo, max_session_bars=dhi,
                        allowed_hours=None, min_rank_momentum=None,
                    ))
    # Deduplicate by name preserving order
    seen = set()
    out = []
    for r in rules:
        if r.name not in seen:
            seen.add(r.name)
            out.append(r)
    return out


def build_exit_grid() -> list[ExitRule]:
    rules: list[ExitRule] = []
    for sl in [0.6, 0.8, 1.0, 1.2, 1.5]:
        for bars in [6, 8, 10, 12, 18]:
            # BE+Trail combo (best from prior analysis)
            rules.append(ExitRule(
                name=f"sl{sl}_be0.6_tr0.9x0.4_t{bars}",
                sl_pct=sl, tp_pct=None, time_stop_bars=bars,
                breakeven_after_pct=0.6, trail_start_pct=0.9, trail_giveback_pct=0.4,
            ))
            rules.append(ExitRule(
                name=f"sl{sl}_be0.8_tr1.2x0.6_t{bars}",
                sl_pct=sl, tp_pct=None, time_stop_bars=bars,
                breakeven_after_pct=0.8, trail_start_pct=1.2, trail_giveback_pct=0.6,
            ))
    seen = set()
    out = []
    for r in rules:
        if r.name not in seen:
            seen.add(r.name)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Backtest + scoring
# ---------------------------------------------------------------------------

def score(entry: EntryRule, exit_: ExitRule, sessions: dict) -> dict | None:
    trades = []
    for sid, rows in sessions.items():
        ok, idx, price, _ = entry_ok(rows, entry)
        if not ok or price <= 0:
            continue
        ret, reason, bars = simulate_exit(rows, idx, price, exit_)
        if reason == "no_exit_bar":
            continue
        trades.append({"gross": ret, "reason": reason, "bars": bars})

    if not trades:
        return None

    gross = [t["gross"] for t in trades]
    net = [r - ROUND_TRIP_COST_PCT for r in gross]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    gp = sum(wins)
    gl = -sum(losses) if losses else 0.0
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)

    return {
        "entry_name": entry.name,
        "exit_name": exit_.name,
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
        "exit_reasons": dict(Counter(t["reason"] for t in trades)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-trades", type=int, default=30, help="minimum closed trades to consider")
    ap.add_argument("--top", type=int, default=10, help="how many top strategies to print")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    stats, sessions = load_sessions(args.db)
    print(f"DB loaded: {stats['dataset_rows']} rows, {stats['sessions']} sessions, "
          f"range {stats['min_ts_iso']} -> {stats['max_ts_iso']}", flush=True)

    entries = build_entry_grid()
    exits = build_exit_grid()
    print(f"Scanning {len(entries)} entries x {len(exits)} exits = {len(entries)*len(exits)} combos ...", flush=True)

    results: list[dict] = []
    for i, entry in enumerate(entries):
        for exit_ in exits:
            res = score(entry, exit_, sessions)
            if res and res["closed_trades"] >= args.min_trades:
                results.append(res)
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(entries)} entry rules ...", flush=True)

    if not results:
        print("No strategy met min_trades threshold.")
        return

    # Sort by win_rate desc, then net_avg_return desc, then trades desc
    results.sort(key=lambda r: (r["win_rate"], r["net_avg_return"], r["closed_trades"]), reverse=True)

    print(f"\nTotal qualifying strategies: {len(results)}\n")
    print("=" * 90)
    print(f"TOP {args.top} by WIN RATE over full 23-day history:")
    print("=" * 90)
    for rank, r in enumerate(results[:args.top], 1):
        print(f"\n#{rank}  Win Rate: {r['win_rate']:.1f}%  (PF={r['profit_factor']:.2f}, Net={r['net_avg_return']:.3f}%)")
        print(f"     Entry: {r['entry_name']}")
        print(f"     Exit : {r['exit_name']}")
        print(f"     Trades: {r['closed_trades']}  Wins: {r['wins']}  Losses: {r['losses']}")
        print(f"     Max Loss: {r['max_loss']:.3f}%  Max DD proxy: {r['max_drawdown_proxy']:.3f}%")
        print(f"     Exit reasons: {r['exit_reasons']}")

    # Also dump full ranking to JSON for inspection
    out_path = Path("data/local_strategy_scan_23d.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull ranking written to: {out_path}")


if __name__ == "__main__":
    main()
