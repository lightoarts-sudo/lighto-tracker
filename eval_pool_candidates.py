#!/usr/bin/env python3
"""Evaluate strategy pool candidates with full backtest."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

# Stub heavy imports
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
if "fastapi" not in sys.modules:
    class _DummyFastAPI:
        def __init__(self, *args, **kwargs):
            pass
        def get(self, *args, **kwargs):
            return lambda fn: fn
        def post(self, *args, **kwargs):
            return lambda fn: fn
        def on_event(self, *args, **kwargs):
            return lambda fn: fn
    def _Query(default=None, *args, **kwargs):
        return default
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_DummyFastAPI, Query=_Query)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)

import crypto_bot as cb
from backtest_top10_active_strategies import Backtester, DEFAULT_STRATEGIES

# Load pool candidates
pool_path = Path("data/strategy_pool.json")
pool = json.loads(pool_path.read_text(encoding="utf-8"))

pending = [c for c in pool["candidates"] if c.get("status") == "pending_review"]
print(f"Found {len(pending)} pending candidates")

# Map existing strategies to avoid duplicates
existing = set(cb.MICRO_TOP10_OPTIMIZED_STRATEGIES.keys())

results = []

for cand in pending:
    cid = cand["id"]
    entry = cand["entry"]
    exit_ = cand["exit"]
    
    # Generate strategy ID in the naming convention
    entry_name = entry["name"]
    exit_name = exit_["name"]
    strategy_id = f"cand_{cid}_{entry_name}_{exit_name}"
    
    # Convert to MICRO_TOP10_OPTIMIZED_STRATEGIES format
    params = {
        "version": "pool_candidate",
        "entry_delay_bars": entry["delay_bars"],
        "max_rank": entry["max_entry_rank"],
        "min_change_1h_pct": entry["min_entry_change"],
        "max_change_1h_pct": entry["max_entry_change"],
        "min_current_change_1h_pct": 0.0,  # not in pool entry
        "require_change_reclaim": False,   # not in pool entry
        "require_green_confirm": entry["require_green_confirm"],
        "max_upper_wick_pct": entry["max_upper_wick_pct"],
        "min_volume_ratio": entry["min_vol_ratio"],
        "reclaim_entry_price": entry.get("reclaim_entry_price", False),
        "shadow_only": False,
        "stop_loss_pct": exit_["sl_pct"],
        "breakeven_after_pct": exit_["breakeven_after_pct"],
        "trailing_start_pct": exit_["trail_start_pct"],
        "trailing_giveback_pct": exit_["trail_giveback_pct"],
        "time_stop_bars": exit_["time_stop_bars"],
    }
    
    # Add to strategies dict temporarily
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy_id] = params
    print(f"Added {strategy_id}")

# Run backtest for all candidates + existing strategies we care about
# Use only our candidate strategies for speed
candidate_strats = [f"cand_{c['id']}_{c['entry']['name']}_{c['exit']['name']}" for c in pending]

# Also test against full DEFAULT_STRATEGIES for comparison (but skip missing ones)
test_strategies = candidate_strats.copy()
for s in DEFAULT_STRATEGIES:
    if s in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES:
        test_strategies.append(s)

print(f"Testing strategies: {test_strategies}")

bt = Backtester("data/okx_micro_5m_tracking.sqlite", test_strategies, min_trades=30)
out = bt.run()

# Print summaries for our candidates
for summary in out["summaries"]:
    strat = summary["strategy"]
    if strat.startswith("cand_"):
        print(f"\n=== {strat} ===")
        print(f"  Closed trades: {summary['closed_trades']}")
        print(f"  Win rate: {summary['win_rate']:.2f}%")
        print(f"  Profit factor: {summary['profit_factor']:.2f}")
        print(f"  Net avg return: {summary['net_avg_return']:.4f}%")
        print(f"  Max loss: {summary['max_loss']:.4f}%")
        print(f"  Exit reasons: {summary['exit_reason_counts']}")
        print(f"  Eligible (trades>=30 & WR>40%): {summary['eligible_win_rate_gt_40']}")

        # Check thresholds
        passes = (
            summary["closed_trades"] >= 30 and
            summary["win_rate"] > 40.0 and
            summary["profit_factor"] > 1.5 and
            summary["net_avg_return"] > 0.0 and
            summary["max_loss"] > -2.0
        )
        print(f"  PASSES THRESHOLDS: {passes}")
        
        results.append({
            "strategy": strat,
            "summary": summary,
            "passes": passes
        })

# Save results
out_path = Path("data/pool_evaluation_latest.json")
out_path.write_text(json.dumps({
    "evaluated_at": __import__("datetime").datetime.now().isoformat(),
    "results": results
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nResults saved to {out_path}")
