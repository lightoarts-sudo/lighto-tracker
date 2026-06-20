#!/usr/bin/env python3
import json
from pathlib import Path

obj = json.loads(Path('data/top10_1h_optimizer_latest.json').read_text())
seen = []
for r in obj['top']:
    seen.append({
        'win_rate': r['win_rate'],
        'net_avg_return': r['net_avg_return'],
        'profit_factor': r['profit_factor'],
        'max_loss': r['max_loss'],
        'closed_trades': r['closed_trades'],
        'entry_name': r['entry']['name'],
        'exit_name': r['exit']['name']
    })
for i,r in enumerate(seen[:20],1):
    print(f"{i}. trades={r['closed_trades']} win={r['win_rate']:.2f} net={r['net_avg_return']:.3f} pf={r['profit_factor']:.2f} maxL={r['max_loss']:.3f} entry={r['entry_name']} exit={r['exit_name']}")
