#!/usr/bin/env python3
"""Quick backtest of the three pool candidates on full history."""
from __future__ import annotations
import sys
sys.path.insert(0, '.')
from tmp_top10_training_optimizer import load_sessions, EntryRule, ExitRule, entry_ok, simulate_exit, ROUND_TRIP_COST_PCT

stats, sessions = load_sessions('data/okx_micro_5m_tracking.sqlite')
print(f"Total sessions: {len(sessions)} (closed: {stats['closed_sessions']})")

candidates = [
    ('cand_4h_20260613_1608_01',
     EntryRule('delay3_rank3_chg3-10_green_vol_dur10-40', 3, 3, 3, 10, True, 1.2, 1.5, False, None, None, None, 10, 40, None),
     ExitRule('sl1.0_be0.6_trail0.9x0.4_t8', 1.0, None, 8, 0.6, 0.9, 0.4)),
    ('cand_4h_20260613_1608_02',
     EntryRule('delay3_rank3_chg3-10_green_vol_reclaim_dur10-40', 3, 3, 3, 10, True, 0.8, 2.0, True, None, None, None, 10, 40, None),
     ExitRule('sl1.0_be0.6_trail0.9x0.4_t8', 1.0, None, 8, 0.6, 0.9, 0.4)),
    ('cand_4h_20260613_1608_03',
     EntryRule('delay3_rank3_chg3-10_green_vol_dur8-50', 3, 3, 3, 10, True, 1.2, 1.5, False, None, None, None, 8, 50, None),
     ExitRule('sl1.0_be0.6_trail0.9x0.4_t8', 1.0, None, 8, 0.6, 0.9, 0.4)),
]

for cid, er, xr in candidates:
    entry_points = []
    for sid, rows in sessions.items():
        ok, idx, price, _ = entry_ok(rows, er)
        if ok and price > 0:
            entry_points.append((sid, rows, idx, price))
    
    if not entry_points:
        print(f"\n=== {cid} === NO ENTRIES")
        continue
    
    trades = []
    for sid, rows, idx, price in entry_points:
        ret, reason, bars = simulate_exit(rows, idx, price, xr)
        if reason == "no_exit_bar":
            continue
        trades.append({"session_id": sid, "gross_return_pct": ret, "exit_reason": reason, "bars_held": bars})
    
    if not trades:
        print(f"\n=== {cid} === NO TRADES AFTER EXIT")
        continue
    
    gross = [t['gross_return_pct'] for t in trades]
    net = [r - ROUND_TRIP_COST_PCT for r in gross]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    gp = sum(wins)
    gl = -sum(losses) if losses else 0
    pf = gp / gl if gl > 0 else float('inf')
    net_avg = sum(net) / len(net)
    max_loss = min(net)
    wr = len(wins) / len(net) * 100
    exit_reasons = {}
    for t in trades:
        exit_reasons[t['exit_reason']] = exit_reasons.get(t['exit_reason'], 0) + 1
    
    print(f"\n=== {cid} ===")
    print(f"  Trades: {len(trades)}")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Net Avg Return: {net_avg:.3f}% (after {ROUND_TRIP_COST_PCT}% cost)")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Loss: {max_loss:.2f}%")
    print(f"  Gross Profit: {gp:.2f}%, Gross Loss: {gl:.2f}%")
    print(f"  Exit reasons: {exit_reasons}")

    # Sanity check: compare with optimizer metrics
    print("  (Optimizer metrics from pool:")
    if cid == 'cand_4h_20260613_1608_01':
        print("   trades=18, wr=66.7%, net=1.811%, pf=6.47, max_loss=-1.2%)")
    elif cid == 'cand_4h_20260613_1608_02':
        print("   trades=11, wr=63.6%, net=1.766%, pf=6.34, max_loss=-1.2%)")
    else:
        print("   trades=21, wr=66.7%, net=1.622%, pf=5.78, max_loss=-1.2%)")

EOF