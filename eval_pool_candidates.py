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

for i, cand in enumerate(pending):
    cid = cand["id"]
    entry = cand["entry"]
    exit_ = cand["exit"]
    
    # Generate strategy ID with "auto_top" prefix so reclaim logic works
    strategy_id = f"auto_top{i+1}_4h_from_pool_{cid.replace('cand_', '')}"
    
    # Convert to MICRO_TOP10_OPTIMIZED_STRATEGIES format
    # Only include params that the production signal function supports
    params = {
        "version": "auto_top_from_pool",
        "entry_delay_bars": entry["delay_bars"],
        "max_rank": entry["max_entry_rank"],
        "min_change_1h_pct": entry["min_entry_change"],
        "max_change_1h_pct": entry["max_entry_change"],
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": entry["require_green_confirm"],
        "max_upper_wick_pct": entry["max_upper_wick_pct"],
        "min_volume_ratio": entry["min_vol_ratio"],
        "reclaim_entry_price": entry.get("reclaim_entry_price", False),
        "shadow_only": False,
        # Exit params
        "stop_loss_pct": exit_["sl_pct"],
        "breakeven_after_pct": exit_["breakeven_after_pct"],
        "trailing_start_pct": exit_["trail_start_pct"],
        "trailing_giveback_pct": exit_["trail_giveback_pct"],
        "time_stop_bars": exit_["time_stop_bars"],
        # Note: min_session_bars, max_session_bars, min_rank_momentum, min_atr_proxy, max_atr_proxy, allowed_hours
        # are not supported in production signal function yet
    }
    
    # Add to strategies dict temporarily
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy_id] = params
    print(f"Added {strategy_id}")

# Run backtest for all candidates
candidate_strats = [f"auto_top{i+1}_4h_from_pool_{c['id'].replace('cand_', '')}" for i, c in enumerate(pending)]

# Also test against existing active strategies for comparison
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
    if strat.startswith("auto_top") and "from_pool" in strat:
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
