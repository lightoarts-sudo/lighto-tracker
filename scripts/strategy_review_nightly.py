#!/usr/bin/env python3
"""LIGHTOARTS lightweight nightly review (read-only).

- Uses existing local SQLite sessions / rankings / candles
- Produces a Markdown report for human review
- Does NOT modify strategy_pool, active_strategies, or trigger live rules
"""

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "okx_micro_5m_tracking.sqlite"
REPORT_PATH = ROOT / "data" / "nightly_review_latest.md"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, captured_at, universe_count, ranked_count, top10_count, topn_count, notes FROM top10_1h_training_runs ORDER BY id DESC")
    runs = [
        {
            "id": r[0],
            "captured_at": r[1],
            "universe_count": r[2],
            "ranked_count": r[3],
            "top10_count": r[4],
            "topn_count": r[5],
            "notes": r[6],
        }
        for r in cur.fetchall()
    ]
    cur.execute(
        """
        SELECT r.run_id, r.inst_id, r.base_ccy, r.rank_1h, r.change_1h_pct, r.quote_vol_24h,
               r.candle_count, s.id, s.entered_at, s.entered_ts_ms, s.entry_rank_1h,
               s.entry_change_1h_pct, s.entry_price, s.entry_signal_rank, s.entry_is_signal_top5,
               s.exited_at, s.exit_reason, s.post_exit_bars_remaining, s.last_seen_at,
               s.last_rank_1h, s.last_change_1h_pct, s.last_price, s.max_change_1h_pct,
               s.min_rank_1h, s.candle_count, s.is_active
        FROM top10_1h_training_rankings r
        LEFT JOIN top10_1h_training_sessions s
          ON s.inst_id = r.inst_id
        ORDER BY r.run_id DESC, r.rank_1h ASC
        """
    )
    rankings = []
    sessions = []
    for row in cur.fetchall():
        rankings.append(
            {
                "run_id": row[0],
                "inst_id": row[1],
                "base_ccy": row[2],
                "rank_1h": row[3],
                "change_1h_pct": row[4],
                "quote_vol_24h": row[5],
                "candle_count": row[6],
            }
        )
        if row[7] is not None:
            sessions.append(
                {
                    "run_id": row[0],
                    "inst_id": row[1],
                    "session_id": row[7],
                    "entered_at": row[8],
                    "entered_ts_ms": row[9],
                    "entry_rank_1h": row[10],
                    "entry_change_1h_pct": row[11],
                    "entry_price": row[12],
                    "entry_signal_rank": row[13],
                    "entry_is_signal_top5": row[14],
                    "exited_at": row[15],
                    "exit_reason": row[16],
                    "post_exit_bars_remaining": row[17],
                    "last_seen_at": row[18],
                    "last_rank_1h": row[19],
                    "last_change_1h_pct": row[20],
                    "last_price": row[21],
                    "max_change_1h_pct": row[22],
                    "min_rank_1h": row[23],
                    "candle_count": row[24],
                    "is_active": row[25],
                }
            )
    cur.execute(
        """
        SELECT session_id, inst_id, ts_iso, open, high, low, close, vol, vol_ccy,
               rank_1h, change_1h_pct
        FROM top10_1h_training_candles
        ORDER BY session_id ASC, ts_iso ASC
        """
    )
    candles = [
        {
            "session_id": row[0],
            "inst_id": row[1],
            "ts_iso": row[2],
            "open": row[3],
            "high": row[4],
            "low": row[5],
            "close": row[6],
            "vol": row[7],
            "vol_ccy": row[8],
            "rank_1h": row[9],
            "change_1h_pct": row[10],
        }
        for row in cur.fetchall()
    ]
    con.close()
    return {"runs": runs, "rankings": rankings, "sessions": sessions, "candles": candles}


def fmt_pct(x):
    try:
        return f"{x:.2f}%"
    except Exception:
        return "—"


def build_report(data: dict) -> str:
    now = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    runs = data["runs"]
    sessions = data["sessions"]
    candles = data["candles"]

    latest_run_id = runs[0]["id"] if runs else None
    latest_run_rankings = [r for r in data["rankings"] if r["run_id"] == latest_run_id] if latest_run_id else []
    # dedupe by inst_id within the latest run, keep the first/best rank only
    seen = set()
    deduped = []
    for r in latest_run_rankings:
        key = r["inst_id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    latest_run_rankings = deduped
    latest_run_candles = [c for c in candles if c["session_id"] is not None] if sessions else []

    # Summaries
    total_runs = len(runs)
    total_sessions = len(sessions)
    active_sessions = [s for s in sessions if s["is_active"] == 1]
    closed_sessions = [s for s in sessions if s["is_active"] != 1]
    exit_reasons = Counter((s.get("exit_reason") or "unknown") for s in closed_sessions)
    profit_sessions = [s for s in closed_sessions if (s.get("last_price") or 0) > (s.get("entry_price") or 0)]
    loss_sessions = [s for s in closed_sessions if (s.get("last_price") or 0) <= (s.get("entry_price") or 0)]

    # Latest Top10
    top10 = latest_run_rankings[:10]

    # Candle coverage
    session_candle_counts = Counter(c["session_id"] for c in candles)
    max_session_candles = max(session_candle_counts.values()) if session_candle_counts else 0

    lines = []
    lines.append("# LIGHTOARTS nightly strategy review")
    lines.append("")
    lines.append(f"- generatedAt: {now}")
    lines.append(f"- db: {DB_PATH}")
    lines.append("")
    lines.append("## Dataset snapshot")
    lines.append("")
    lines.append(f"- training runs: {total_runs}")
    lines.append(f"- sessions total: {total_sessions}")
    lines.append(f"- sessions active: {len(active_sessions)}")
    lines.append(f"- sessions closed: {len(closed_sessions)}")
    lines.append(f"- closed session win approximation: {len(profit_sessions)}/{len(closed_sessions)}" if closed_sessions else "- closed session win approximation: —")
    lines.append(f"- max candles in any single session: {max_session_candles}")
    lines.append("")

    lines.append("## Latest run")
    lines.append("")
    if runs:
        latest = runs[0]
        lines.append(f"- run id: {latest['id']}")
        lines.append(f"- capturedAt: {latest['captured_at']}")
        lines.append(f"- universe: {latest['universe_count']}")
        lines.append(f"- ranked: {latest['ranked_count']}")
        lines.append(f"- top10: {latest['top10_count']}")
        lines.append(f"- topn: {latest['topn_count']}")
        lines.append(f"- notes: {latest['notes'] or ''}")
    lines.append("")
    lines.append("## Latest Top10")
    lines.append("")
    if top10:
        lines.append("| rank | inst_id | base | chg_1h | vol_24h | candles |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in top10:
            lines.append(
                f"| {r['rank_1h']} | {r['inst_id']} | {r['base_ccy']} | {fmt_pct(r.get('change_1h_pct'))} | {fmt_pct(r.get('quote_vol_24h'))} | {r.get('candle_count') or '—'} |"
            )
    else:
        lines.append("_No Top10 data._")
    lines.append("")

    lines.append("## Sessions")
    lines.append("")
    lines.append("| session_id | inst_id | entered | exit | exit_reason | candles | price change |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for s in sessions[:20]:
        entry_p = s.get("entry_price") or 0.0
        last_p = s.get("last_price") or 0.0
        chg = ((last_p - entry_p) / entry_p * 100.0) if entry_p else 0.0
        lines.append(
            f"| {s['session_id']} | {s['inst_id']} | {s.get('entered_at','') or ''} | {s.get('exited_at','') or ''} | {s.get('exit_reason','') or ''} | {s.get('candle_count') or '—'} | {fmt_pct(chg)} |"
        )
    if len(sessions) > 20:
        lines.append(f"- (_showing 20 of {len(sessions)} sessions)")
    lines.append("")

    lines.append("## Exit reasons")
    lines.append("")
    for reason, count in exit_reasons.most_common():
        lines.append(f"- {reason}: {count}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    data = load()
    report = build_report(data)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
