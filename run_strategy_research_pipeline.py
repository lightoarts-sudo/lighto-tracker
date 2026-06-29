#!/usr/bin/env python3
"""LIGHTOARTS 新策略研發流程。

用途：在不改變 DB 抓取規則、不自動部署、不下 OKX 實盤的前提下，
每日把「資料蒐集 -> 因子/策略產生 -> 回測 -> 嚴格篩選 -> 研究報告」標準化。

流程：
1. 檢查 DB 品質與資料量
2. 更新 TopN/Top5 訓練資料（使用 okx_top10_1h_training_collector）
3. 跑 Strategy Scanner / Optimizer（本地回測）
4. 寫入 strategy_pool.json
5. 產生研究報告
6. 回報結果
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(r"C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker")

DB_PATH = PROJECT / "data" / "okx_micro_5m_tracking.sqlite"
POOL_PATH = PROJECT / "data" / "strategy_pool.json"
REPORT_PATH = PROJECT / "docs" / "strategy_research_daily_report.md"
LIVE_STANDARD_PATH = PROJECT / "data" / "live_strategy_standard.json"

MIN_SESSIONS = 50
MIN_CANDLES = 1000
MIN_SESSION_MINUTES = 30
LIVE_STANDARDS = {
    "min_trades": 0,
    "min_win_rate_pct": 40.0,
    "min_profit_factor": 1.5,
    "max_loss_pct": -2.0,
    "min_net_avg_return_pct": 0.0,
    "require_samples_over_time": True,
}


def ensure_stubs() -> None:
    if "asyncpg" not in sys.modules:
        sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
    if "fastapi" not in sys.modules:
        class _FA:
            def __init__(self, *a, **kw): ...
            def get(self, *a, **kw): return lambda fn: fn
            def post(self, *a, **kw): return lambda fn: fn
            def on_event(self, *a, **kw): return lambda fn: fn
        sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_FA, Query=lambda *a, **kw: None)
        sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(PROJECT),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def check_db_quality() -> dict[str, Any]:
    import sqlite3

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    stats: dict[str, Any] = {}
    for key, sql in {
        "runs": "select count(*) from top10_1h_training_runs",
        "rankings": "select count(*) from top10_1h_training_rankings",
        "sessions": "select count(*) from top10_1h_training_sessions",
        "closed_sessions": "select count(*) from top10_1h_training_sessions where is_active=0",
        "active_sessions": "select count(*) from top10_1h_training_sessions where is_active=1",
        "candles_5m": "select count(*) from candles_5m",
        "candles_1h": "select count(*) from top10_1h_training_candles",
        "short_closed_sessions": "select count(*) from top10_1h_training_sessions where is_active=0 and (exited_ts_ms - entered_ts_ms)/60000.0 < ?",
        "eligible_ge_30m_sessions": "select count(*) from top10_1h_training_sessions where is_active=0 and (exited_ts_ms - entered_ts_ms)/60000.0 >= ?",
    }.items():
        if "short_closed_sessions" == key or "eligible_ge_30m_sessions" == key:
            stats[key] = con.execute(sql, (MIN_SESSION_MINUTES,)).fetchone()[0]
        else:
            stats[key] = con.execute(sql).fetchone()[0]
    row = con.execute("select min(captured_at), max(captured_at) from top10_1h_training_runs").fetchone()
    stats["first_run"] = row[0]
    stats["last_run"] = row[1]
    stats["ok"] = (
        stats["eligible_ge_30m_sessions"] >= 30
        and stats["candles_5m"] >= MIN_CANDLES
        and stats["last_run"] is not None
    )
    con.close()
    return stats


def update_training_data() -> dict[str, Any]:
    proc = run_cmd(
        [
            sys.executable,
            str(PROJECT / "okx_top10_1h_training_collector.py"),
            "--max-rank",
            "20",
            "--entry-rank",
            "5",
            "--post-exit-bars",
            "12",
            "--sleep",
            "0.02",
        ]
    )
    if proc.returncode != 0:
        return {"ok": False, "stderr": proc.stderr[-1000:]}
    try:
        return {"ok": True, "result": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": proc.stdout[-1000:]}


def scan_candidates() -> dict[str, Any]:
    proc = run_cmd([sys.executable, str(PROJECT / "local_strategy_scanner.py"), "--min-trades", "0", "--top", "20"])
    if proc.returncode != 0:
        return {"ok": False, "stderr": proc.stderr[-1000:]}
    if not proc.stdout.strip():
        return {"ok": False, "stderr": proc.stderr[-1000:]}
    try:
        return {"ok": True, "result": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": proc.stdout[-1000:]}


def backtest_pool() -> dict[str, Any]:
    proc = run_cmd([sys.executable, str(PROJECT / "local_backtest_topn.py"), "--min-trades", "0", "--top", "20"])
    if proc.returncode != 0:
        return {"ok": False, "stderr": proc.stderr[-1000:]}
    if not proc.stdout.strip():
        return {"ok": False, "stderr": proc.stderr[-1000:]}
    try:
        return {"ok": True, "result": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": proc.stdout[-1000:]}


def load_pool() -> dict[str, Any]:
    if POOL_PATH.exists():
        return json.loads(POOL_PATH.read_text(encoding="utf-8"))
    return {"updated_at": "", "candidates": []}


def save_pool(pool: dict[str, Any]) -> None:
    pool["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    POOL_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_candidates_from_scan(scan: dict[str, Any]) -> int:
    pool = load_pool()
    existing_keys = set()
    for cand in pool["candidates"]:
        en = cand.get("entry", {}).get("name", "") if isinstance(cand.get("entry"), dict) else cand.get("entry_name", "")
        xn = cand.get("exit", {}).get("name", "") if isinstance(cand.get("exit"), dict) else cand.get("exit_name", "")
        existing_keys.add(f"{en}|{xn}")

    added = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = scan.get("top", scan.get("results", [])) if isinstance(scan, dict) else []
    for rank, item in enumerate(items[:20], 1):
        en = item.get("entry_name") or (item.get("entry") or {}).get("name", "")
        xn = item.get("exit_name") or (item.get("exit") or {}).get("name", "")
        key = f"{en}|{xn}"
        if not key.strip("|") or key in existing_keys:
            continue
        pool["candidates"].append(
            {
                "id": f"cand_{datetime.now().strftime('%Y%m%d_%H%M')}_{rank:02d}",
                "created_at": now,
                "entry": item.get("entry") or {"name": en},
                "exit": item.get("exit") or {"name": xn},
                "metrics": {
                    "trades": item.get("trades") or item.get("closed_trades"),
                    "win_rate": item.get("win_rate"),
                    "profit_factor": item.get("profit_factor"),
                    "net_avg_return": item.get("net_avg_return"),
                    "max_loss": item.get("max_loss"),
                },
                "status": "pending_review",
                "rejection_reason": "",
                "evaluated_at": "",
                "source": "daily_21h_research_pipeline",
            }
        )
        existing_keys.add(key)
        added += 1
    if added:
        save_pool(pool)
    return added


def evaluate_against_live_standard(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified = []
    for cand in candidates:
        m = cand.get("metrics", {}) or {}
        trades = m.get("trades") or m.get("closed_trades") or 0
        win_rate = (m.get("win_rate") or 0.0)
        pf = m.get("profit_factor") or 0.0
        max_loss = (m.get("max_loss") or 0.0)
        net_return = (m.get("net_avg_return") or 0.0)
        if (
            trades >= LIVE_STANDARDS["min_trades"]
            and win_rate >= LIVE_STANDARDS["min_win_rate_pct"]
            and pf >= LIVE_STANDARDS["min_profit_factor"]
            and max_loss >= LIVE_STANDARDS["max_loss_pct"]
            and net_return > LIVE_STANDARDS["min_net_avg_return_pct"]
        ):
            cand["status"] = "live_ready"
            cand["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            qualified.append(cand)
        else:
            reasons = []
            if trades < LIVE_STANDARDS["min_trades"]:
                reasons.append(f"trades {trades} < {LIVE_STANDARDS['min_trades']}")
            if win_rate < LIVE_STANDARDS["min_win_rate_pct"]:
                reasons.append(f"win_rate {win_rate:.1f}% < {LIVE_STANDARDS['min_win_rate_pct']}%")
            if pf < LIVE_STANDARDS["min_profit_factor"]:
                reasons.append(f"PF {pf:.2f} < {LIVE_STANDARDS['min_profit_factor']}")
            if max_loss < LIVE_STANDARDS["max_loss_pct"]:
                reasons.append(f"max_loss {max_loss:.2f}% >= {LIVE_STANDARDS['max_loss_pct']}%")
            if net_return <= LIVE_STANDARDS["min_net_avg_return_pct"]:
                reasons.append(f"net_avg {net_return:.3f}% <= {LIVE_STANDARDS['min_net_avg_return_pct']}%")
            cand["status"] = "pending_review"
            cand["rejection_reason"] = "; ".join(reasons)
            cand["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return qualified


def build_report(db_stats: dict[str, Any], scan_meta: dict[str, Any], backtest_meta: dict[str, Any], pool: dict[str, Any]) -> str:
    today = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        f"# 策略研發日報 ({today})",
        "",
        "## 1. DB 狀態",
        "",
        f"- sessions: {db_stats.get('sessions', 0):,}",
        f"- closed_sessions: {db_stats.get('closed_sessions', 0):,}",
        f"- active_sessions: {db_stats.get('active_sessions', 0):,}",
        f"- candles_5m: {db_stats.get('candles_5m', 0):,}",
        f"- last_run: {db_stats.get('last_run')}",
        "",
        "## 2. 資料品質",
        "",
        "✅ 通過" if db_stats.get("ok") else "❌ 資料不足，請確認 collector 正常運行",
        "",
        "## 3. Strategy Scan / Backtest",
        "",
        f"- scan_ok: {scan_meta.get('ok')}",
        f"- backtest_ok: {backtest_meta.get('ok')}",
        "",
        "## 4. 策略池",
        "",
        f"- updated_at: {pool.get('updated_at')}",
        f"- candidates: {len(pool.get('candidates', []))}",
        "",
        "## 5. 可用樣本集",
        "",
        f"- eligible_ge_30m_sessions（>= 30 分鐘）：{db_stats.get('eligible_ge_30m_sessions', 0):,}",
        f"- 已排除短 session：{db_stats.get('short_closed_sessions', 0):,}",
        "- 合格門檻：session 持續 >= 30 分鐘",
        "",
        "## 5. 可進入真錢條件審核的策略",
        "",
        "條件：",
        f"- min_trades={LIVE_STANDARDS['min_trades']}",
        f"- win_rate>={LIVE_STANDARDS['min_win_rate_pct']}%",
        f"- profit_factor>={LIVE_STANDARDS['min_profit_factor']}",
        f"- max_loss>={LIVE_STANDARDS['max_loss_pct']}%",
        f"- net_avg_return>{LIVE_STANDARDS['min_net_avg_return_pct']}%",
        "",
    ]
    candidates = pool.get("candidates", [])
    live_ready = [c for c in candidates if c.get("status") == "live_ready"]
    if live_ready:
        lines.append("| ID | 進場規則 | 出場規則 | 交易數 | 勝率% | PF | 淨期望% | 最大虧損% |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in live_ready[:20]:
            en = c.get("entry", {})
            xn = c.get("exit", {})
            m = c.get("metrics", {}) or {}
            e_name = en.get("name", "") if isinstance(en, dict) else (en or "")
            x_name = xn.get("name", "") if isinstance(xn, dict) else (xn or "")
            lines.append(
                f"| {c.get('id','')} "
                f"| {e_name} "
                f"| {x_name} "
                f"| {m.get('trades',0)} "
                f"| {float(m.get('win_rate') or 0):.1f} "
                f"| {float(m.get('profit_factor') or 0):.2f} "
                f"| {float(m.get('net_avg_return') or 0):.3f} "
                f"| {float(m.get('max_loss') or 0):.2f} |"
            )
    else:
        lines.append("目前無符合真錢條件的新策略。")
    lines += ["", "## 6. 不合格策略（前 10）", ""]
    not_ready = [c for c in candidates if c.get("status") != "live_ready"]
    if not_ready:
        lines.append("| ID | 原因 |")
        lines.append("|---|---|")
        for c in not_ready[:10]:
            lines.append(f"| {c.get('id','')} | {c.get('rejection_reason','')} |")
    else:
        lines.append("-")
    lines += ["", "> 本報告為研究用途，不自動部署或下單。", ""]
    return "\n".join(lines)


def main() -> int:
    print("[1/6] check_db_quality")
    db_stats = check_db_quality()
    print(db_stats)

    print("[2/6] update_training_data")
    update_res = update_training_data()
    print(update_res.get("ok"))

    print("[3/6] scan_candidates")
    scan_res = scan_candidates()
    print(scan_res.get("ok"), type(scan_res.get("result")).__name__ if isinstance(scan_res.get("result"), dict) else "")

    print("[4/6] backtest_pool")
    backtest_res = backtest_pool()
    print(backtest_res.get("ok"))

    print("[5/6] upsert_candidates_from_scan")
    scan_payload = scan_res.get("result") if isinstance(scan_res.get("result"), dict) else {}
    added = upsert_candidates_from_scan(scan_payload)
    print("added", added)

    print("[6/6] evaluate + report")
    pool = load_pool()
    qualified = evaluate_against_live_standard(pool.get("candidates", []))
    pool["candidates"] = pool.get("candidates", [])
    save_pool(pool)

    report = build_report(db_stats, scan_res, backtest_res, pool)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "db_stats": db_stats,
        "added_candidates": added,
        "live_ready": len(qualified),
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
