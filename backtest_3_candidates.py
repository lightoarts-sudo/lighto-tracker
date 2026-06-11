#!/usr/bin/env python3
"""Quick backtest of 3 candidate strategies from daily scan."""

import sys
import types

# Stub asyncpg/fastapi before importing crypto_bot
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

# The 3 candidate strategies in MICRO_TOP10_OPTIMIZED_STRATEGIES format
# Need to map from daily scan naming to micro_top10_optimized naming

# Candidate 1: top5_r1_5_chg3_8_vol0_sl1_tr08x04_h6_cap3
# -> delay=1, max_entry_rank=3, min_chg=3, max_chg=12 (for d1), cur1/2, sl1, tr0.8x0.4, t6
# Actually looking at MICRO_TOP10_OPTIMIZED_STRATEGIES in crypto_bot:
# format: top10scan{d}_r{rmax}_chg{chgmin}_{chgmax}_cur{cur}_sl{sl}_tr{trail_start}x{trail_giveback}_t{hold}

# Let's check what strategies exist in MICRO_TOP10_OPTIMIZED_STRATEGIES
print("Available MICRO_TOP10_OPTIMIZED_STRATEGIES:")
for k in cb.MICRO_TOP10_OPTIMIZED_STRATEGIES.keys():
    print(f"  {k}")