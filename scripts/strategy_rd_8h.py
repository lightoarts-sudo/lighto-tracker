#!/usr/bin/env python3
"""Lightweight 8h strategy R&D loop (local DB only).

Reads closed sessions from local SQLite, grids a small candidate set from
built-in baseline parameters, backtests each candidate, and writes:
- data/strategy_rd_8h_latest.md
- data/strategy_rd_8h_latest.json
- data/strategy_rd_8h_history.jsonl

This does NOT modify strategy_pool, active_strategies, or trigger live rules.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "okx_micro_5m_tracking.sqlite"
REPORT_MD = ROOT / "data" / "strategy_rd_8h_latest.md"
REPORT_JSON = ROOT / "data" / "strategy_rd_8h_latest.json"
HISTORY_JSONL = ROOT / "data" / "strategy_rd_8h_history.jsonl"
ROUND_TRIP_COST_PCT = 0.16
MIN_TRADES = 0


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


def load_optimizer() -> tuple:
    _ensure_fastapi_stub()
    from tmp_top10_training_optimizer import (
        EntryRule,
        ExitRule,
        load_sessions,
        entry_ok,
        simulate_exit,
        summarize,
    )
    return EntryRule, ExitRule, load_sessions, entry_ok, simulate_exit, summarize


def build_candidates() -> tuple[list, list]:
    EntryRule, ExitRule, *_ = load_optimizer()
    entries: list[EntryRule] = []
    exits: list[ExitRule] = []

    # Baseline dynamic entry (best-fit to 5m data).
    for delay_bars in [2, 3]:
        for max_entry_rank in [3, 5]:
            for lo, hi in [(2, 10), (3, 10)]:
                entries.append(EntryRule(
                    f"d{delay_bars}_r{max_entry_rank}_{lo}-{hi}_gv",
                    delay_bars=delay_bars,
                    max_entry_rank=max_entry_rank,
                    min_entry_change=lo,
                    max_entry_change=hi,
                    require_green_confirm=True,
                    max_upper_wick_pct=1.2,
                    min_vol_ratio=1.0,
                    reclaim_entry_price=False,
                ))
                entries.append(EntryRule(
                    f"d{delay_bars}_r{max_entry_rank}_{lo}-{hi}_rec",
                    delay_bars=delay_bars,
                    max_entry_rank=max_entry_rank,
                    min_entry_change=lo,
                    max_entry_change=hi,
                    require_green_confirm=True,
                    max_upper_wick_pct=1.2,
                    min_vol_ratio=1.0,
                    reclaim_entry_price=True,
                ))
                for dmin, dmax in [(6, 60), (10, 40)]:
                    entries.append(EntryRule(
                        f"d{delay_bars}_r{max_entry_rank}_{lo}-{hi}_gv_d{dmin}-{dmax}",
                        delay_bars=delay_bars,
                        max_entry_rank=max_entry_rank,
                        min_entry_change=lo,
                        max_entry_change=hi,
                        require_green_confirm=True,
                        max_upper_wick_pct=1.2,
                        min_vol_ratio=1.0,
                        reclaim_entry_price=False,
                        min_session_bars=dmin,
                        max_session_bars=dmax,
                    ))

    # Cross-factor entry variants: atr x vol x hour x rank_momentum
    # Each variant reuses a base entry shape, then adds one extra filter so the
    # optimizer can later rank interactions, not just single-factor winners.
    delay = 2
    for max_entry_rank in [3, 5]:
        for lo, hi in [(2, 10), (3, 10)]:
            base_kwargs = {
                "delay_bars": delay,
                "max_entry_rank": max_entry_rank,
                "min_entry_change": lo,
                "max_entry_change": hi,
                "require_green_confirm": True,
                "max_upper_wick_pct": 1.2,
                "min_vol_ratio": 1.0,
                "reclaim_entry_price": False,
            }
            # Vol-strength variants
            vol15 = dict(base_kwargs)
            vol15["min_vol_ratio"] = 1.5
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_vol1.5",
                **vol15,
            ))
            vol20 = dict(base_kwargs)
            vol20["min_vol_ratio"] = 2.0
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_vol2.0",
                **vol20,
            ))
            # Tight-wick breakout variants
            w08 = {**base_kwargs, "max_upper_wick_pct": 0.8}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_w0.8",
                **w08,
            ))
            w08_vol15 = {**base_kwargs, "max_upper_wick_pct": 0.8, "min_vol_ratio": 1.5}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_w0.8_vol1.5",
                **w08_vol15,
            ))
            # Volatility regime via ATR proxy
            atr = {**base_kwargs, "min_atr_proxy": 1.0, "max_atr_proxy": 3.0}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_atr1-3",
                **atr,
            ))
            atr_w08_vol15 = {
                **base_kwargs,
                "min_atr_proxy": 1.0,
                "max_atr_proxy": 3.0,
                "max_upper_wick_pct": 0.8,
                "min_vol_ratio": 1.5,
            }
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_atr1-3_w0.8",
                **atr_w08_vol15,
            ))
            # Session-length quantile variant
            d1020 = {**base_kwargs, "min_session_bars": 10, "max_session_bars": 20}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_d10-20",
                **d1020,
            ))
            # Time-of-day window: UTC 12:00-20:00 approx Asia evening / US morning
            hod = {**base_kwargs, "allowed_hours": (12, 13, 14, 15, 16, 17, 18, 19)}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_h120-200",
                **hod,
            ))
            # Rank momentum filter: require rank improved by >=2 bars within 4 bars
            mom = {**base_kwargs, "min_rank_momentum": 2}
            entries.append(EntryRule(
                f"d{delay}_r{max_entry_rank}_{lo}-{hi}_gv_mom2",
                **mom,
            ))

    # Baseline exits
    for sl in [0.8, 1.0, 1.2]:
        for bars in [8, 12, 18]:
            exits.append(ExitRule(
                name=f"sl{sl}_be0.6_t0.9x0.4_t{bars}",
                sl_pct=sl,
                tp_pct=None,
                time_stop_bars=bars,
                breakeven_after_pct=0.6,
                trail_start_pct=0.9,
                trail_giveback_pct=0.4,
            ))
            exits.append(ExitRule(
                name=f"sl{sl}_be0.8_t1.2x0.6_t{bars}",
                sl_pct=sl,
                tp_pct=None,
                time_stop_bars=bars,
                breakeven_after_pct=0.8,
                trail_start_pct=1.2,
                trail_giveback_pct=0.6,
            ))

    # Cross-factor exit variants: tp + trailing + time_stop
    for sl in [0.8, 1.0, 1.2]:
        for tp in [0.8, 1.2]:
            for trail in [(0.6, 0.3), (0.9, 0.4), (1.2, 0.6)]:
                for bars in [12]:
                    exits.append(ExitRule(
                        name=f"sl{sl}_tp{tp}_tr{trail[0]}x{trail[1]}_t{bars}",
                        sl_pct=sl,
                        tp_pct=tp,
                        time_stop_bars=bars,
                        breakeven_after_pct=None,
                        trail_start_pct=trail[0],
                        trail_giveback_pct=trail[1],
                    ))

    seen = set()
    unique_entries = []
    for e in entries:
        if e.name in seen:
            continue
        seen.add(e.name)
        unique_entries.append(e)
    seen.clear()
    unique_exits = []
    for e in exits:
        if e.name in seen:
            continue
        seen.add(e.name)
        unique_exits.append(e)
    return unique_entries, unique_exits


def run_backtest(db_path: str) -> dict:
    EntryRule, ExitRule, load_sessions_fn, entry_ok, simulate_exit, summarize = load_optimizer()
    stats, sessions = load_sessions_fn(db_path)
    if stats["closed_sessions"] == 0:
        return {"db_stats": stats, "candidates": [], "skipped": "no closed sessions"}
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
                trades.append({
                    "session_id": sid,
                    "gross_return_pct": ret,
                    "exit_reason": reason,
                    "bars_held": bars,
                })
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
    return {"db_stats": stats, "candidates": candidates[:20], "candidate_count": len(candidates)}


def build_report(payload: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stats = payload["db_stats"]
    lines = [
        "# LIGHTOARTS 8h strategy R&D",
        "",
        f"- generatedAt: {now}",
        f"- db: {DB_PATH}",
        f"- datasetRows: {stats.get('dataset_rows', '')}",
        f"- sessions: {stats.get('sessions', '')} (closed {stats.get('closed_sessions', '')})",
        f"- insts: {stats.get('insts', '')}",
        f"- timeRange: {stats.get('min_ts_iso', '')} ~ {stats.get('max_ts_iso', '')}",
        "",
        "## Top candidates",
    ]
    if not payload["candidates"]:
        lines.append("")
        lines.append("_No candidate passed minimum trade threshold._")
        return "\n".join(lines) + "\n"

    lines.extend([
        "",
        "| rank | id | entry | exit | trades | wr | net% | PF | maxLoss |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for i, c in enumerate(payload["candidates"], 1):
        lines.append(
            f"| {i} | {c.get('id','')} | {c['entry']['name']} | {c['exit']['name']} | {c['closed_trades']} | {c['win_rate']:.1f}% | {c['net_avg_return']:.3f}% | {c['profit_factor']:.2f} | {c['max_loss']:.3f}% |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = run_backtest(str(DB_PATH))
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(build_report(payload), encoding="utf-8")
    with HISTORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(payload.get("candidates", [])),
            "closed_sessions": payload["db_stats"].get("closed_sessions"),
        }, ensure_ascii=False) + "\n")
    detail_path = REPORT_JSON.parent / "strategy_rd_8h_history_candidates.jsonl"
    with detail_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "db_stats": payload.get("db_stats", {}),
            "candidates": payload.get("candidates", [])[:20],
        }, ensure_ascii=False) + "\n")
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
