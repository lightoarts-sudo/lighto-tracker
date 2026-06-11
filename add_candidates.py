#!/usr/bin/env python3
"""Add 3 candidate strategies to MICRO_TOP10_OPTIMIZED_STRATEGIES and run backtest."""

import sys
import types

# Stub asyncpg/fastapi BEFORE importing crypto_bot
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

# Add the 3 candidate strategies
# Candidate 1: top5_r1_5_chg3_8_vol0_sl1_tr08x04_h6_cap3
# Maps to: top5 family, rank 1-5, chg 3-8, sl1, trail 0.8x0.4, hold 6
# But MICRO_TOP10 only has top10scan variants (rank 1-3 or 1-5, chg 3-12)
# Let's create closest equivalent: top5scan_d1_r5_chg3_8_cur0_sl1_tr08x04_t6

CANDIDATE_1 = "top5scan_d1_r5_chg3_8_cur0_sl1_tr08x04_t6"
if CANDIDATE_1 not in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES:
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[CANDIDATE_1] = {
        "version": "top5scan",
        "entry_delay_bars": 1,
        "max_rank": 5,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 8.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "min_volume_ratio": 0.0,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.8,
        "trailing_start_pct": 0.8,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 6,
    }
    print(f"Added: {CANDIDATE_1}")

# Candidate 2: pretop11_30 - can't test with top10_1h_training_rankings (only has 1-10)
# Skip - no rank 11-30 data in training DB

# Candidate 3: top10_r1_10_chg2_5_vol0_sl08_tr1x05_h18_cap3
# Maps to: top10 family, rank 1-10, chg 2-5, sl0.8, trail 1.0x0.5, hold 18
# But existing top10scan only go to rank 3 or 5. Need rank 1-10.
CANDIDATE_3 = "top10scan_d1_r10_chg2_5_cur0_sl08_tr1x05_t18"
if CANDIDATE_3 not in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES:
    cb.MICRO_TOP10_OPTIMIZED_STRATEGIES[CANDIDATE_3] = {
        "version": "top10scan_wide",
        "entry_delay_bars": 1,
        "max_rank": 10,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 5.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "min_volume_ratio": 0.0,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 1.0,
        "trailing_start_pct": 1.0,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 18,
    }
    print(f"Added: {CANDIDATE_3}")

# Also test the closest existing top10scan that matches candidate 1's params
# top10scan1: delay=1, rank=3, chg=3-12, cur=1, sl=1, trail=1.5x0.5, t12
# Our candidate: delay=1, rank=5, chg=3-8, cur=0, sl=1, trail=0.8x0.4, t6
# Different enough to be separate

# Check existing similar
print("\nExisting top10scan variants:")
for k, v in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES.items():
    if k.startswith("top10scan") and not k.startswith("top10scan_d"):
        print(f"  {k}: rank={v['max_rank']}, chg={v['min_change_1h_pct']}-{v['max_change_1h_pct']}, cur={v.get('min_current_change_1h_pct')}, sl={v['stop_loss_pct']}, trail={v['trailing_start_pct']}x{v['trailing_giveback_pct']}, t{v['time_stop_bars']}")

print("\nDone adding candidates. Now run backtest_import.py")