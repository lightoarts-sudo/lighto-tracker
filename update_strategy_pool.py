#!/usr/bin/env python3
"""Write 4H optimizer results to strategy_pool.json as pending_review candidates."""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(r"C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker")
_4H = PROJECT / "data" / "top10_1h_optimizer_latest_4h.json"
_LEGACY = PROJECT / "data" / "top10_1h_optimizer_latest.json"
OPTIMIZER_RESULTS = _4H if _4H.exists() else _LEGACY
POOL_FILE = PROJECT / "data" / "strategy_pool.json"


def load_optimizer_results():
    with open(OPTIMIZER_RESULTS, "r") as f:
        return json.load(f)


def load_pool():
    if POOL_FILE.exists():
        with open(POOL_FILE, "r") as f:
            return json.load(f)
    return {"updated_at": "", "candidates": []}


def save_pool(pool):
    pool["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(POOL_FILE, "w") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def main():
    results = load_optimizer_results()
    pool = load_pool()
    
    top3 = results.get("top", [])[:3]
    if not top3:
        print("No optimizer results to add to pool")
        return
    
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    
    # Build set of existing candidate keys for fast duplicate detection
    existing_keys = set()
    for existing in pool["candidates"]:
        entry_name = existing.get("entry", {}).get("name", "")
        exit_name = existing.get("exit", {}).get("name", "")
        existing_keys.add(f"{entry_name}|{exit_name}")
    
    for i, r in enumerate(top3, 1):
        entry = r["entry"]
        exit_ = r["exit"]
        
        key = f"{entry['name']}|{exit_['name']}"
        
        if key in existing_keys:
            print(f"Skipped duplicate: {entry['name']} + {exit_['name']}")
            continue
        
        candidate = {
            "id": f"cand_4h_{datetime.now().strftime('%Y%m%d_%H%M')}_{i:02d}",
            "created_at": now,
            "entry": entry,
            "exit": exit_,
            "metrics": {
                "trades": r.get("closed_trades") or r.get("entries"),
                "win_rate": r.get("win_rate"),
                "profit_factor": r.get("profit_factor"),
                "net_avg_return": r.get("net_avg_return"),
                "max_loss": r.get("max_loss"),
            },
            "status": "pending_review",
            "rejection_reason": "",
            "evaluated_at": "",
            "source": "4h_optimizer",
        }
        
        pool["candidates"].append(candidate)
        existing_keys.add(key)
        added += 1
        print(f"Added candidate: {candidate['id']}")
    
    if added > 0:
        save_pool(pool)
        print(f"Updated strategy_pool.json with {added} new pending_review candidates")
    else:
        print("No new candidates added (all duplicates)")


if __name__ == "__main__":
    main()
