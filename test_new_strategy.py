#!/usr/bin/env python3
"""Test best strategy from sweep: d2_r3_chg2-8_green_sl2_tr0.8x0.4_t18 (WR=69.5%, PF=1.07)"""

import sys, types
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
if "fastapi" not in sys.modules:
    class _DummyFastAPI:
        def __init__(self, *args, **kwargs): pass
        def get(self, *args, **kwargs): return lambda fn: fn
        def post(self, *args, **kwargs): return lambda fn: fn
        def on_event(self, *args, **kwargs): return lambda fn: fn
    def _Query(default=None, *args, **kwargs): return default
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_DummyFastAPI, Query=_Query)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)

import crypto_bot as cb

# Add the sweep winner strategy
STRATEGY_NAME = "sweep_best_d2_r3_chg2-8_green_sl2_tr0.8x0.4_t18"
if STRATEGY_NAME not in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES:
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[STRATEGY_NAME] = {
        "version": "sweep_best",
        "entry_delay_bars": 2,
        "max_rank": 3,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 8.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "shadow_only": False,
        "stop_loss_pct": 2.0,
        "breakeven_after_pct": 999.0,
        "trailing_start_pct": 0.8,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 18,
    }
    print(f"Added {STRATEGY_NAME}")

# Also test a refined version with reclaim + uw filter
STRATEGY_NAME2 = "sweep_refined_d2_r3_chg2-8_green_uw12_reclaim_sl1.2_be0.8_tr1.2x0.5_t12"
if STRATEGY_NAME2 not in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES:
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[STRATEGY_NAME2] = {
        "version": "sweep_refined",
        "entry_delay_bars": 2,
        "max_rank": 3,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 8.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "reclaim_entry_price": True,
        "min_volume_ratio": 0.0,
        "shadow_only": False,
        "stop_loss_pct": 1.2,
        "breakeven_after_pct": 0.8,
        "trailing_start_pct": 1.2,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    }
    print(f"Added {STRATEGY_NAME2}")

print("Done - now run backtest")