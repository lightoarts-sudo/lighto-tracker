import json

with open('data/top10_1h_optimizer_latest.json') as f:
    data = json.load(f)

criteria = {
    'net_avg_return': 0,
    'profit_factor': 1.5,
    'max_loss': -2,
    'win_rate': 40,
    'closed_trades': 30
}

print('=== 優化器前 10 名策略篩選結果 ===')
print()
qualified = []
for i, r in enumerate(data['top'][:10], 1):
    entry = r['entry']
    exit = r['exit']
    name = f'{entry["name"]} + {exit["name"]}'
    
    checks = {
        'net_avg_return > 0': r['net_avg_return'] > criteria['net_avg_return'],
        'profit_factor > 1.5': r['profit_factor'] > criteria['profit_factor'],
        'max_loss > -2%': r['max_loss'] > criteria['max_loss'],
        'win_rate > 40%': r['win_rate'] > criteria['win_rate'],
        'closed_trades >= 30': r['closed_trades'] >= criteria['closed_trades'],
    }
    all_pass = all(checks.values())
    status = '✓ 合格' if all_pass else '✗ 不合格'
    if not all_pass:
        failed = [k for k, v in checks.items() if not v]
        status += f' ({", ".join(failed)})'
    
    print(f'{i}. {name}')
    print(f'   net_avg_return: {r["net_avg_return"]:.4f}%, profit_factor: {r["profit_factor"]:.2f}, max_loss: {r["max_loss"]:.2f}%, win_rate: {r["win_rate"]:.1f}%, trades: {r["closed_trades"]}')
    print(f'   {status}')
    print()
    if all_pass:
        qualified.append((i, r))

print(f'合格策略數: {len(qualified)}')
print('前 3 名合格策略:')
for i, (rank, r) in enumerate(qualified[:3], 1):
    entry = r['entry']
    exit = r['exit']
    print(f'  auto_top{i}_4h: {entry["name"]} + {exit["name"]} (net_avg_return: {r["net_avg_return"]:.4f}%)')

# Save qualified for later use
import pickle
with open('data/qualified_strategies.pkl', 'wb') as f:
    pickle.dump(qualified[:3], f)
