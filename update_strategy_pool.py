import json
from datetime import datetime

# Read the optimizer results
with open('tmp_top10_training_optimizer_results.json', 'r', encoding='utf-8') as f:
    results = json.load(f)

# Filter criteria
candidates = []
for i, r in enumerate(results['top'][:10]):
    trades = r['closed_trades']
    win_rate = r['win_rate']
    profit_factor = r['profit_factor']
    net_avg_return = r['net_avg_return']
    max_loss = r['max_loss']
    
    if (trades >= 10 and 
        win_rate > 45 and 
        profit_factor > 1.3 and 
        net_avg_return > 0 and 
        max_loss > -1.5):
        
        # Generate ID: cand_4h_YYYYMMDD_HHMM_NN
        now = datetime.now()
        candidate_id = f"cand_4h_{now.strftime('%Y%m%d_%H%M')}_{i+1:02d}"
        
        candidates.append({
            "id": candidate_id,
            "created_at": now.isoformat(),
            "entry_name": r['entry']['name'],
            "exit_name": r['exit']['name'],
            "metrics": {
                "trades": trades,
                "win_rate": round(win_rate, 1),
                "profit_factor": round(profit_factor, 2),
                "net_avg_return": round(net_avg_return, 2),
                "max_loss": round(max_loss, 1)
            },
            "status": "pending_review"
        })

# Update strategy pool - keep only top 3
pool = {
    "updated_at": datetime.now().isoformat(),
    "candidates": candidates[:3]
}

with open('data/strategy_pool.json', 'w', encoding='utf-8') as f:
    json.dump(pool, f, ensure_ascii=False, indent=2)

print(f"Found {len(candidates)} eligible candidates, keeping top 3")
for c in candidates[:3]:
    m = c['metrics']
    print(f"  {c['id']}: entry={c['entry_name']}, exit={c['exit_name']}, trades={m['trades']}, win_rate={m['win_rate']}%, pf={m['profit_factor']}, net_avg={m['net_avg_return']}, max_loss={m['max_loss']}%")