#!/usr/bin/env python
"""Production-style 5m replay for pre-Top10 takeoff candidates.

This is the stricter second gate after `scan_pretop30_takeoff_strategies.py`.
It starts from implementable rank 11-30 signals only, then replays real 5m
candles with stop/slippage/cooldown/blacklist guards similar to the OKX pilot.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from scan_pretop30_takeoff_strategies import Params, candidate_events, load_snapshots

FEE_ROUND_TRIP_PCT = 0.16
DEFAULT_STRATEGIES = [
    # Best 5m-replay plateau from the pre-Top10 scan: modest 1H heat, real
    # volume, tight hard stops, and a shorter 3h time stop instead of waiting
    # for the whole snapshot-level 6h window.
    Params(11, 30, 1.0, 2.0, 1.0, 6, 0.6, False, 0),
    Params(11, 30, 1.0, 2.0, 1.0, 6, 0.8, False, 0),
    Params(16, 20, 1.0, 2.0, 0.5, 6, 1.2, False, 0),
]


@dataclass(frozen=True)
class ReplayGuards:
    hold_bars: int = 36  # 36 * 5m = 3h; shorter hold reduced giveback in 5m replay.
    slippage_each_side_pct: float = 0.04
    cooldown_minutes: int = 180
    max_entries_per_inst_12h: int = 1
    blacklist_loss_threshold_pct: float = -1.0
    blacklist_loss_count: int = 2
    blacklist_hours: int = 24
    min_trades: int = 20


def parse_ts_ms(ts: str) -> int:
    text = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def event_matches(event: dict, p: Params) -> bool:
    return (
        p.rank_min <= event["rank"] <= p.rank_max
        and p.chg_min <= event["chg"] <= p.chg_max
        and event["vol_ratio"] >= p.vol_min
        and not p.require_enter_top10
    )


def load_future_candles(con: sqlite3.Connection, inst_id: str, entry_ms: int, hold_bars: int):
    return [
        dict(r)
        for r in con.execute(
            """
            select ts_ms, ts_iso, open, high, low, close, vol, vol_ccy
            from candles_5m
            where inst_id=? and ts_ms>? 
            order by ts_ms asc
            limit ?
            """,
            (inst_id, entry_ms, hold_bars),
        )
    ]


def replay_event_5m(con: sqlite3.Connection, event: dict, p: Params, guards: ReplayGuards):
    entry_ms = parse_ts_ms(event["ts"])
    candles = load_future_candles(con, event["inst_id"], entry_ms, guards.hold_bars)
    if not candles:
        return None

    buy_slip = guards.slippage_each_side_pct / 100.0
    sell_slip = guards.slippage_each_side_pct / 100.0
    entry_ref = float(event["price"])
    entry_px = entry_ref * (1 + buy_slip)
    stop_px = entry_px * (1 - p.stop_pct / 100.0)
    exit_ref = float(candles[-1]["close"])
    exit_reason = "time_stop"
    exit_ts = candles[-1]["ts_iso"]
    mae = 0.0
    mfe = 0.0

    for c in candles:
        low = float(c["low"])
        high = float(c["high"])
        mae = min(mae, (low / entry_px - 1) * 100.0)
        mfe = max(mfe, (high / entry_px - 1) * 100.0)
        if low <= stop_px:
            exit_ref = stop_px
            exit_reason = "hard_stop"
            exit_ts = c["ts_iso"]
            break

    exit_px = exit_ref * (1 - sell_slip)
    gross = (exit_px / entry_px - 1) * 100.0
    net = gross - FEE_ROUND_TRIP_PCT
    return {
        "strategy": p.name,
        "inst_id": event["inst_id"],
        "entry_ts": event["ts"],
        "entry_ts_ms": entry_ms,
        "exit_ts": exit_ts,
        "entry_rank": event["rank"],
        "entry_change_1h_pct": event["chg"],
        "entry_vol_ratio": event["vol_ratio"],
        "entry_ref_price": entry_ref,
        "entry_price_after_slippage": entry_px,
        "exit_price_after_slippage": exit_px,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "mae_pct": mae,
        "mfe_pct": mfe,
    }


def passes_guards(event: dict, guard_state: dict, guards: ReplayGuards):
    inst = event["inst_id"]
    ts_ms = parse_ts_ms(event["ts"])
    if ts_ms < guard_state["blacklist_until"].get(inst, 0):
        return False, "blacklisted"
    if ts_ms < guard_state["cooldown_until"].get(inst, 0):
        return False, "cooldown"
    recent = [t for t in guard_state["entry_times"].get(inst, []) if ts_ms - t < 12 * 60 * 60 * 1000]
    guard_state["entry_times"][inst] = recent
    if len(recent) >= guards.max_entries_per_inst_12h:
        return False, "max_entries_12h"
    return True, "ok"


def update_guards(trade: dict, guard_state: dict, guards: ReplayGuards):
    inst = trade["inst_id"]
    entry_ms = trade["entry_ts_ms"]
    guard_state["entry_times"].setdefault(inst, []).append(entry_ms)
    if trade["net_return_pct"] <= 0 or trade["exit_reason"] == "hard_stop":
        guard_state["cooldown_until"][inst] = max(
            guard_state["cooldown_until"].get(inst, 0),
            entry_ms + guards.cooldown_minutes * 60 * 1000,
        )
    if trade["net_return_pct"] <= guards.blacklist_loss_threshold_pct:
        losses = [t for t in guard_state["loss_times"].get(inst, []) if entry_ms - t < 12 * 60 * 60 * 1000]
        losses.append(entry_ms)
        guard_state["loss_times"][inst] = losses
        if len(losses) >= guards.blacklist_loss_count:
            guard_state["blacklist_until"][inst] = max(
                guard_state["blacklist_until"].get(inst, 0),
                entry_ms + guards.blacklist_hours * 60 * 60 * 1000,
            )


def summarize(strategy: Params, trades: list[dict], skipped: Counter, guards: ReplayGuards):
    vals = [t["net_return_pct"] for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    days = defaultdict(float)
    reasons = Counter()
    inst = defaultdict(float)
    for t in trades:
        days[t["entry_ts"][:10]] += t["net_return_pct"]
        reasons[t["exit_reason"]] += 1
        inst[t["inst_id"]] += t["net_return_pct"]
    return {
        "strategy": strategy.name,
        "params": asdict(strategy),
        "guards": asdict(guards),
        "trades": len(trades),
        "win_rate": len(wins) / len(vals) * 100 if vals else 0.0,
        "net_avg_return": sum(vals) / len(vals) if vals else 0.0,
        "median_net_return": median(vals) if vals else 0.0,
        "profit_factor": gp / gl if gl else 999.0,
        "max_loss": min(vals) if vals else 0.0,
        "day_win_rate": sum(1 for v in days.values() if v > 0) / len(days) * 100 if days else 0.0,
        "worst_day": min(days.values()) if days else 0.0,
        "best_day": max(days.values()) if days else 0.0,
        "exit_reason_counts": dict(reasons),
        "skipped_guard_counts": dict(skipped),
        "worst_instruments": sorted(inst.items(), key=lambda kv: kv[1])[:5],
        "best_instruments": sorted(inst.items(), key=lambda kv: kv[1], reverse=True)[:5],
        "render_shadow_candidate": (
            len(trades) >= guards.min_trades
            and (sum(vals) / len(vals) if vals else 0.0) > 0.05
            and (gp / gl if gl else 999.0) >= 1.2
            and (min(vals) if vals else 0.0) >= -2.5
            and (sum(1 for v in days.values() if v > 0) / len(days) * 100 if days else 0.0) >= 45.0
        ),
    }


def replay_strategy(con: sqlite3.Connection, snaps: list[dict], strategy: Params, guards: ReplayGuards):
    trades = []
    skipped = Counter()
    guard_state = {"cooldown_until": {}, "blacklist_until": {}, "entry_times": {}, "loss_times": {}}
    for event in candidate_events(snaps):
        if not event_matches(event, strategy):
            continue
        ok, reason = passes_guards(event, guard_state, guards)
        if not ok:
            skipped[reason] += 1
            continue
        trade = replay_event_5m(con, event, strategy, guards)
        if not trade:
            skipped["no_future_candles"] += 1
            continue
        trades.append(trade)
        update_guards(trade, guard_state, guards)
    return summarize(strategy, trades, skipped, guards), trades


def run_replay(db_path: str, guards: ReplayGuards, strategies=None):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    snaps = load_snapshots(con)
    strategies = strategies or DEFAULT_STRATEGIES
    summaries = []
    trades_by_strategy = {}
    for strategy in strategies:
        summary, trades = replay_strategy(con, snaps, strategy, guards)
        summaries.append(summary)
        trades_by_strategy[strategy.name] = trades
    summaries.sort(key=lambda s: (s["render_shadow_candidate"], s["net_avg_return"], s["profit_factor"], s["trades"]), reverse=True)
    return {
        "db": db_path,
        "snapshot_count": len(snaps),
        "first_snapshot": snaps[0]["ts"] if snaps else None,
        "last_snapshot": snaps[-1]["ts"] if snaps else None,
        "fee_round_trip_pct": FEE_ROUND_TRIP_PCT,
        "summaries": summaries,
        "trades_by_strategy": trades_by_strategy,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/okx_micro_5m_tracking.sqlite")
    ap.add_argument("--json-out", default="data/pretop30_takeoff_5m_replay_latest.json")
    ap.add_argument("--csv-out", default="data/pretop30_takeoff_5m_replay_latest.csv")
    ap.add_argument("--hold-bars", type=int, default=36)
    ap.add_argument("--slippage-each-side-pct", type=float, default=0.04)
    ap.add_argument("--cooldown-minutes", type=int, default=180)
    args = ap.parse_args()

    guards = ReplayGuards(
        hold_bars=args.hold_bars,
        slippage_each_side_pct=args.slippage_each_side_pct,
        cooldown_minutes=args.cooldown_minutes,
    )
    out = run_replay(args.db, guards)
    Path(args.json_out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    fields = [
        "strategy", "trades", "win_rate", "net_avg_return", "median_net_return",
        "profit_factor", "max_loss", "day_win_rate", "worst_day", "best_day",
        "render_shadow_candidate",
    ]
    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in out["summaries"]:
            w.writerow({k: s[k] for k in fields})
    compact = {**out, "trades_by_strategy": {k: len(v) for k, v in out["trades_by_strategy"].items()}}
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
