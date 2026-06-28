#!/usr/bin/env python3
"""Track a named strategy across 8h R&D history and append CSV rows."""

import csv
import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY = ROOT / "data" / "strategy_rd_8h_history_candidates.jsonl"
REPORT = ROOT / "data" / "strategy_rd_8h_latest.json"
TARGET_ENTRY = "d2_r3_3-10_gv_atr1-3_w0.8"
TARGET_EXIT = "sl0.8_tp1.2_tr1.2x0.6_t12"
REPORT_TS = ROOT / "data" / "strategy_rd_8h_latest.md"
DAILY_COUNTS = ROOT / "data" / "strategy_rd_8h_daily_counts.csv"
TOTAL_COUNT = ROOT / "data" / "strategy_rd_8h_total_daily_trades.csv"

def load_history():
    if not HISTORY.exists():
        return []
    rows=[]
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            print(f"history json err: {e}")
            rows=[]
    return rows

def load_latest():
    if not REPORT.exists():
        return {}
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"latest json err: {e}")
        return {}
    
def load_ts_from_report():
    if not REPORT_TS.exists():
        return ""
    try:
        for line in REPORT_TS.read_text(encoding="utf-8").splitlines():
            s=line.strip()
            if s.startswith("- generatedAt:"):
                return s.split(":",1)[1].strip()
    except Exception:
        pass
    return ""

def find_target(history):
    best=None
    for row in history:
        for c in row.get("candidates", []):
            e=(c.get("entry") or {}).get("name","")
            x=(c.get("exit") or {}).get("name","")
            if e==TARGET_ENTRY and x==TARGET_EXIT:
                lock={
                    "ts": row.get("ts"),
                    "closed_sessions": (row.get("db_stats") or {}).get("closed_sessions"),
                    "closed_trades": c.get("closed_trades"),
                    "wins": c.get("wins"),
                    "losses": c.get("losses"),
                    "win_rate": c.get("win_rate"),
                    "net_avg_return": c.get("net_avg_return"),
                    "profit_factor": c.get("profit_factor"),
                    "max_loss": c.get("max_loss"),
                }
                if best is None or (lock.get("ts") or "") > (best.get("ts") or ""):
                    best=lock
    return best

def find_today_target(history):
    today=datetime.now().strftime("%Y-%m-%d")
    rows=[]
    for row in history:
        ts=row.get("ts","")
        if not ts.startswith(today):
            continue
        for c in row.get("candidates", []):
            e=(c.get("entry") or {}).get("name","")
            x=(c.get("exit") or {}).get("name","")
            if e==TARGET_ENTRY and x==TARGET_EXIT:
                rows.append(row)
                break
    return rows

def count_candidate_names(history):
    today=datetime.now().strftime("%Y-%m-%d")
    counts={}
    for row in history:
        ts=row.get("ts","")
        if not ts.startswith(today):
            continue
        for c in row.get("candidates", []):
            e=(c.get("entry") or {}).get("name","")
            x=(c.get("exit") or {}).get("name","")
            if not (isinstance(c.get("entry"), dict) and isinstance(c.get("exit"), dict)):
                continue
            if e==TARGET_ENTRY and x==TARGET_EXIT:
                counts["d2_r3_3-10_gv_atr1-3_w0.8 / sl0.8_tp1.2_tr1.2x0.6_t12"] = counts.get("d2_r3_3-10_gv_atr1-3_w0.8 / sl0.8_tp1.2_tr1.2x0.6_t12", 0) + 1
    return counts

def write_counts_csv_path(path, ts_label, counts):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = (not path.exists() or path.stat().st_size == 0)
    with path.open("a", encoding="utf-8", newline="") as f:
        w=csv.writer(f)
        if write_header:
            w.writerow(["ts_8h", "entry", "exit", "count"])
        for key, value in counts.items():
            entry, exit_ = key.split(" / ")
            w.writerow([ts_label, entry.strip(), exit_.strip(), value])

def total_daily_trades_csv(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in history:
        totals=0
        for c in row.get("candidates", []):
            if isinstance(c.get("entry"), dict) and isinstance(c.get("exit"), dict):
                totals += int(c.get("closed_trades", 0) or 0)
        rows.append([row.get("ts"), totals])
    rows=sorted(rows, key=lambda x: x[0])

    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("w", encoding="utf-8", newline="") as f:
        w=csv.writer(f)
        if write_header:
            w.writerow(["ts_8h", "total_closed_trades"])
        for row in rows:
            w.writerow(row)


if __name__ == "__main__":
    history = load_history()
    latest = load_latest()
    # Show latest report meta
    print(f"NOW: {datetime.now().isoformat()}")
    print(f"REPORT_GENERATEDAT: {load_ts_from_report()}")
    print(f"DB_ROWS: {latest.get('db_stats', {}).get('dataset_rows')}  sessions: {latest.get('db_stats', {}).get('sessions')}  closed: {latest.get('db_stats', {}).get('closed_sessions')}")
    print()
    print("FULLEST_WIDE_NAMES_FROM_HISTORY:")
    newest_targets = {}
    for row in history:
        for c in row.get("candidates", []):
            e=(c.get("entry") or {}).get("name","")
            x=(c.get("exit") or {}).get("name","")
            key = f"{e} / {x}"
            ts = row.get("ts")
            item={
                "ts_8h": ts,
                "uuid": c.get("uuid"),
                "name": c.get("name"),
                "entry": e,
                "exit": x,
                "trades": c.get("closed_trades"),
                "wins": c.get("wins"),
                "losses": c.get("losses"),
                "win_rate": c.get("win_rate"),
                "net_avg_return": c.get("net_avg_return"),
                "profit_factor": c.get("profit_factor"),
                "max_loss": c.get("max_loss"),
                "max_drawdown_proxy": c.get("max_drawdown_proxy"),
                "exit_reason_counts": c.get("exit_reason_counts"),
            }
            readings = newest_targets.get(key)
            if readings is None:
                newest_targets[key]=item
                # 保留最近 5 笔
                latest.setdefault("candidates", [])
                if len(latest.get("candidates", [])) < 5:
                    pass
    for key, item in newest_targets.items():
        print(key)

    print()
    print("TODAY_REPEATED_CANDIDATES d2_r3_3-10_gv_atr1-3_w0.8")
    today_targets = find_today_target(history)
    counts = count_candidate_names(history)
    print(f"{datetime.now().strftime('%Y-%m-%d')}: repeated target strategy count={counts.get('d2_r3_3-10_gv_atr1-3_w0.8 / sl0.8_tp1.2_tr1.2x0.6_t12', len(today_targets))}")
    print(f" More total: {len(history)} rows")
    print()
    print("REPEATED_CANDIDATE_VALUES d2_r3_3-10_gv_atr1-3_w0.8")
    repeated_rows = today_targets
    for row in repeated_rows:
        for item in row.get("candidates", []):
            e=(c.get("entry") or {}).get("name","")
            x=(c.get("exit") or {}).get("name","")
            print(f" {e} / {x}: {item.get('closed_trades')} trades, wr={item.get('win_rate')}% net={item.get('net_avg_return')} pf={item.get('profit_factor')}")
            # 直接覆蓋 counters
            counts[f"{e} / {x}"] = counts.get(f"{e} / {x}", 0) + 1
    print()
    print("REPEATED_CANDIDATE_DETAIL_VIEW:")
    for key, count in counts.items():
        print(key.split(" / ") + [count])

    write_counts_csv_path(DAILY_COUNTS, datetime.now().isoformat(), counts)
    # 汇总 CSV 目前先写入今日开启总收入先算总数
    total_path = TOTAL_COUNT
    today=datetime.now().strftime("%Y-%m-%d")
    total_daily_trades_csv(total_path)
