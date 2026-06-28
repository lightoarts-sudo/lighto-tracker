#!/usr/bin/env python3
"""Sync 8h R&D candidate details into structured monitoring artifacts."""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_CANDIDATES = ROOT / "data" / "strategy_rd_8h_history_candidates.jsonl"
POOL_FILE = ROOT / "data" / "strategy_pool.json"
HISTORY_ROWS = ROOT / "data" / "strategy_rd_8h_history.jsonl"
LATEST_HISTORY = ROOT / "data" / "strategy_rd_8h_latest_history.json"
LATEST_REPORT = ROOT / "data" / "strategy_rd_8h_latest.json"
SNAPSHOT_SKIPS = {"system_generated", "candidate_generated"}

def load_candidates_jsonl():
    if not HISTORY_CANDIDATES.exists():
        return []
    rows = []
    for line in HISTORY_CANDIDATES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            print(f"[sync] skip candidate row: {exc}")
            rows = []
    return rows

def group_rows(rows):
    """Group by date then entry/exit; return latest per group with counts."""
    grouped = defaultdict(list)
    for row in rows:
        ts = (row.get("ts") or "")[:10]
        for c in row.get("candidates", []):
            e = (c.get("entry") or {}).get("name") or ""
            x = (c.get("exit") or {}).get("name") or ""
            grouped[(ts, e, x)].append({"ts": row.get("ts"), "run": row, "candidate": c})
    out = {}
    for (ts, e, x), items in grouped.items():
        items.sort(key=lambda it: it.get("ts") or "", reverse=True)
        out[(ts, e, x)] = items[0]
    return out

def build_latest_history(grouped, latest_jsonl):
    latest_by_date = {}
    for (ts, e, x), item in grouped.items():
        if not ts:
            continue
        if latest_by_date.get(ts, {}).get("ts_8h", "") < (item.get("ts") or ""):
            latest_by_date[ts] = {
                "ts_8h": item.get("ts"),
                "entry": e,
                "exit": x,
                "candidate": item.get("candidate"),
                "db_stats": (item.get("run") or {}).get("db_stats", {}),
            }
    history = sorted(latest_by_date.values(), key=lambda it: it.get("ts_8h", ""))
    with latest_jsonl.open("w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().isoformat(), "history": history}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return history

def update_pool(pool_path, rows):
    now = datetime.now().isoformat()
    history_ts = []
    for row in rows:
        ts = row.get("ts")
        if ts:
            history_ts.append(ts)
    payload = {
        "updated_at": now,
        "last_history_ts": max(history_ts) if history_ts else None,
        "history_ts_count": len(history_ts),
        "history_rows_appended": (json.loads(HISTORY_ROWS.read_text(encoding="utf-8").splitlines()[-1]).get("candidate_count") if HISTORY_ROWS.exists() and HISTORY_ROWS.read_text(encoding="utf-8").strip() else None),
        "candidates": [],
        "status": "synced",
    }
    pool_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_latest_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[sync] latest json err: {e}")
        return {}


def main():
    print(f"[sync] start")
    rows = load_candidates_jsonl()
    print(f"[sync] candidates rows loaded={len(rows)}")
    grouped = group_rows(rows)
    print(f"[sync] unique groups={len(grouped)}")
    history = build_latest_history(grouped, LATEST_HISTORY)
    print(f"[sync] latest_history rows={len(history)}")
    update_pool(POOL_FILE, rows)
    print(f"[sync] strategy_pool.json updated_at=now")
    latest = update_latest_json(LATEST_REPORT)
    total_candidates = len(latest.get("candidates", []))
    top1 = (latest.get("candidates") or [{}])[0]
    print(f"[sync] latest_top1 entry={(top1.get('entry') or {}).get('name')} exit={(top1.get('exit') or {}).get('name')} closed={top1.get('closed_trades')} net={top1.get('net_avg_return')} pf={top1.get('profit_factor')}")
    print(f"[sync] current snapshot candidate_count={total_candidates}")
    print(f"[sync] done -> {LATEST_HISTORY}")


if __name__ == "__main__":
    sys.exit(main())
