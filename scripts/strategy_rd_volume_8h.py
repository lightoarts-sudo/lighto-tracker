#!/usr/bin/env python3
"""Volume Top10 long-only R&D (Phase 1).

Reads 5m candles from volume DB, builds rolling 8h sessions, and evaluates
long-only entry/exit rules.

Outputs:
- data/strategy_rd_volume_latest.md
- data/strategy_rd_volume_latest.json
- data/strategy_rd_volume_history.jsonl
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VOLUME_DB_PATH = ROOT / "data" / "okx_top10_volume_5m_tracking.sqlite"
REPORT_MD = ROOT / "data" / "strategy_rd_volume_latest.md"
REPORT_JSON = ROOT / "data" / "strategy_rd_volume_latest.json"
HISTORY_JSONL = ROOT / "data" / "strategy_rd_volume_history.jsonl"
ROUND_TRIP_COST_PCT = 0.16
MIN_TRADES = 2


def _ensure_fastapi_stub() -> None:
    if "fastapi" in sys.modules:
        return
    sys.modules.setdefault("asyncpg", types.SimpleNamespace(create_pool=None))

    class _FA:
        def __init__(self, *a, **kw):
            pass
        def get(self, *a, **kw):
            return lambda fn: fn
        def post(self, *a, **kw):
            return lambda fn: fn
        def on_event(self, *a, **kw):
            return lambda fn: fn

    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_FA, Query=lambda *a, **kw: None)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)


@dataclass(frozen=True)
class EntryRule:
    name: str
    min_vol_ratio: float | None = None
    max_upper_wick_pct: float | None = None
    require_green: bool = False


@dataclass(frozen=True)
class ExitRule:
    name: str
    sl_pct: float
    tp_pct: float | None = None
    time_stop_bars: int = 12
    breakeven_after_pct: float | None = None
    trail_start_pct: float | None = None
    trail_giveback_pct: float | None = None


def ensure_volume_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS candles_5m (
            inst_id TEXT NOT NULL,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            vol REAL NOT NULL,
            vol_ccy REAL NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY(inst_id, ts_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_vol10_candles_inst_ts ON candles_5m(inst_id, ts_ms);

        CREATE TABLE IF NOT EXISTS volume_sessions_8h (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inst_id TEXT NOT NULL,
            start_ts_ms INTEGER NOT NULL,
            start_ts_iso TEXT NOT NULL,
            end_ts_ms INTEGER,
            end_ts_iso TEXT,
            open REAL NOT NULL,
            close REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            vol REAL NOT NULL,
            vol_ccy REAL NOT NULL,
            return_pct REAL,
            max_return_pct REAL,
            bars INTEGER NOT NULL,
            captured_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vol_sessions_inst ON volume_sessions_8h(inst_id);
        """
    )
    con.commit()


def build_sessions(db_path: Path) -> tuple[dict, dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ensure_volume_schema(con)

    rows = con.execute(
        """
        select * from candles_5m
        where open is not null and high is not null and low is not null and close is not null
        order by inst_id, ts_ms
        """
    ).fetchall()
    con.close()

    by_inst: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_inst.setdefault(row["inst_id"], []).append(row)

    stats = {
        "dataset_rows": len(rows),
        "sessions": 0,
        "insts": len(by_inst),
    }
    sessions: dict[int, list[sqlite3.Row]] = {}
    WINDOW_BARS = 32  # ~2.5 hours of 5m bars

    for inst_id, bars in by_inst.items():
        if len(bars) < WINDOW_BARS + 1:
            continue
        for i in range(len(bars) - WINDOW_BARS):
            window = bars[i : i + WINDOW_BARS]
            session_bar = bars[i + WINDOW_BARS]
            open_ = float(window[0]["open"])
            close = float(window[-1]["close"])
            high = max(float(b["high"]) for b in window)
            low = min(float(b["low"]) for b in window)
            vol = sum(float(b["vol"]) for b in window)
            vol_ccy = sum(float(b["vol_ccy"] or 0.0) for b in window)
            if open_ <= 0 or close <= 0:
                continue
            session_id = len(sessions) + 1
            sessions[session_id] = window + [session_bar]

    stats["sessions"] = len(sessions)
    stats["min_ts_iso"] = rows[0]["ts_iso"] if rows else None
    stats["max_ts_iso"] = rows[-1]["ts_iso"] if rows else None
    return stats, sessions


def build_candidates() -> tuple[list[EntryRule], list[ExitRule]]:
    entries: list[EntryRule] = []
    exits: list[ExitRule] = []

    for min_vol in [1.0, 1.5]:
        for wick in [None, 1.0, 2.0]:
            for green in [False, True]:
                entries.append(
                    EntryRule(
                        name=f"vol{min_vol}_w{wick}_g{int(green)}",
                        min_vol_ratio=min_vol,
                        max_upper_wick_pct=wick,
                        require_green=green,
                    )
                )

    for sl in [0.8, 1.0, 1.2]:
        for trail in [None, (1.0, 0.4), (1.2, 0.6)]:
            for bars in [8, 12]:
                if trail is None:
                    exits.append(ExitRule(name=f"sl{sl}_t{bars}", sl_pct=sl, time_stop_bars=bars))
                else:
                    exits.append(
                        ExitRule(
                            name=f"sl{sl}_tr{trail[0]}x{trail[1]}_t{bars}",
                            sl_pct=sl,
                            time_stop_bars=bars,
                            trail_start_pct=trail[0],
                            trail_giveback_pct=trail[1],
                        )
                    )
    return entries, exits


def bar_return_pct(open_: float, close: float) -> float:
    return ((close - open_) / open_) * 100.0 if open_ else 0.0


def entry_ok(rows: list, rule: EntryRule) -> tuple[bool, int, float, str]:
    if len(rows) < 5:
        return False, -1, 0.0, "not_enough_bars"
    entry_bar = rows[-1]
    open_ = float(entry_bar["open"])
    close = float(entry_bar["close"])
    high = float(entry_bar["high"])
    body_top = max(open_, close)
    if open_ <= 0:
        return False, -1, 0.0, "bad_open"
    if rule.require_green and close <= open_:
        return False, -1, 0.0, "not_green"
    if rule.max_upper_wick_pct is not None:
        upper = ((high - body_top) / body_top) * 100.0 if body_top else 0.0
        if upper > rule.max_upper_wick_pct:
            return False, -1, 0.0, "upper_wick"
    recent_vols = [float(r["vol_ccy"] or r["vol"]) for r in rows[-5:]]
    avg_vol = sum(recent_vols) / len(recent_vols)
    this_vol = float(entry_bar["vol_ccy"] or entry_bar["vol"])
    if rule.min_vol_ratio is not None and avg_vol > 0 and this_vol / avg_vol < rule.min_vol_ratio:
        return False, -1, 0.0, "low_vol"
    return True, len(rows) - 1, close, "ok"


def simulate_exit(rows: list, entry_idx: int, entry_price: float, rule: ExitRule) -> tuple[float, str, int]:
    stop = entry_price * (1.0 - rule.sl_pct / 100.0)
    peak = entry_price
    max_bars = min(len(rows) - 1, entry_idx + rule.time_stop_bars)
    for i in range(entry_idx + 1, max_bars + 1):
        r = rows[i]
        high = float(r["high"])
        low = float(r["low"])
        close = float(r["close"])
        peak = max(peak, high)
        active_stop = stop
        if rule.breakeven_after_pct is not None:
            if ((peak - entry_price) / entry_price) * 100.0 >= rule.breakeven_after_pct:
                active_stop = max(active_stop, entry_price)
        if rule.trail_start_pct is not None:
            if ((peak - entry_price) / entry_price) * 100.0 >= rule.trail_start_pct:
                trail_stop = peak * (1.0 - (rule.trail_giveback_pct or 0.0) / 100.0)
                active_stop = max(active_stop, trail_stop)
        if low <= active_stop:
            return bar_return_pct(active_stop, entry_price), "stop_or_trail", i - entry_idx
        if rule.tp_pct is not None and high >= entry_price * (1.0 + rule.tp_pct / 100.0):
            return rule.tp_pct, "tp", i - entry_idx
    if max_bars > entry_idx:
        close = float(rows[max_bars]["close"])
        return bar_return_pct(close, entry_price), "time_stop", max_bars - entry_idx
    return 0.0, "no_exit_bar", 0


def summarize(trades: list[dict], entry: EntryRule, exit_: ExitRule) -> dict:
    gross = [t["gross_return_pct"] for t in trades]
    net = [r - ROUND_TRIP_COST_PCT for r in gross]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    return {
        "entry": entry.__dict__,
        "exit": exit_.__dict__,
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "avg_return": (sum(gross) / len(gross)) if gross else 0.0,
        "median_return": median(gross) if gross else 0.0,
        "net_avg_return": (sum(net) / len(net)) if net else 0.0,
        "profit_factor": (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0),
        "max_loss": min(net) if net else 0.0,
        "max_drawdown_proxy": 0.0,
        "exit_reason_counts": dict(Counter(t["exit_reason"] for t in trades)),
    }


def run_backtest(db_path: Path) -> dict:
    stats, sessions = build_sessions(db_path)
    entries, exits = build_candidates()
    candidates: list[dict] = []
    for er in entries:
        entry_points = []
        for sid, rows in sessions.items():
            ok, idx, price, _ = entry_ok(rows, er)
            if ok and price > 0:
                entry_points.append((sid, rows, idx, price))
        if not entry_points:
            continue
        for xr in exits:
            trades = []
            for sid, rows, idx, price in entry_points:
                ret, reason, bars = simulate_exit(rows, idx, price, xr)
                if reason == "no_exit_bar":
                    continue
                trades.append(
                    {
                        "session_id": sid,
                        "gross_return_pct": ret,
                        "exit_reason": reason,
                        "bars_held": bars,
                    }
                )
            if len(trades) < MIN_TRADES:
                continue
            candidates.append(summarize(trades, er, xr))

    candidates.sort(
        key=lambda r: (
            r["net_avg_return"],
            r["profit_factor"],
            -r["max_loss"],
            r["win_rate"],
        ),
        reverse=True,
    )
    return {
        "db_stats": stats,
        "candidates": candidates[:20],
        "candidate_count": len(candidates),
    }


def build_report(payload: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stats = payload["db_stats"]
    lines = [
        "# LIGHTOARTS Volume Top10 8h strategy R&D",
        "",
        f"- generatedAt: {now}",
        f"- db: {VOLUME_DB_PATH}",
        f"- datasetRows: {stats.get('dataset_rows', '')}",
        f"- insts: {stats.get('insts', '')}",
        f"- timeRange: {stats.get('min_ts_iso', '')} ~ {stats.get('max_ts_iso', '')}",
        "",
        "## Top candidates",
    ]
    if not payload["candidates"]:
        lines.append("")
        lines.append("_No candidate passed minimum trade threshold._")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "",
            "| rank | entry | exit | trades | wr | net% | PF | maxLoss |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for i, c in enumerate(payload["candidates"], 1):
        lines.append(
            f"| {i} | {c['entry']['name']} | {c['exit']['name']} | {c['closed_trades']} | {c['win_rate']:.1f}% | {c['net_avg_return']:.3f}% | {c['profit_factor']:.2f} | {c['max_loss']:.3f}% |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = run_backtest(VOLUME_DB_PATH)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(build_report(payload), encoding="utf-8")
    with HISTORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "candidate_count": len(payload.get("candidates", [])),
                    "db_stats": payload.get("db_stats", {}),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    best = payload["candidates"][0] if payload.get("candidates") else None
    if best:
        print(
            f"top1={best['entry']['name']} / {best['exit']['name']} "
            f"net={best['net_avg_return']:.3f}% pf={best['profit_factor']:.2f} "
            f"wr={best['win_rate']:.1f}% trades={best['closed_trades']}"
        )
    else:
        print("no qualifying candidate this run")
    print(f"report={REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
