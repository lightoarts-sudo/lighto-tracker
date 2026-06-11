#!/usr/bin/env python3
"""Lightweight optimizer for OKX 1H Top10 training sessions.

Pure Python + sqlite3.  It replays point-in-time rows from
`top10_1h_training_dataset` and only allows entry predicates to inspect bars at
or before the entry/confirmation bar.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

ROUND_TRIP_COST_PCT = 0.16


@dataclass(frozen=True)
class EntryRule:
    name: str
    delay_bars: int
    max_entry_rank: int
    min_entry_change: float
    max_entry_change: float
    require_green_confirm: bool = False
    max_upper_wick_pct: float | None = None
    min_vol_ratio: float | None = None
    reclaim_entry_price: bool = False


@dataclass(frozen=True)
class ExitRule:
    name: str
    sl_pct: float
    tp_pct: float | None = None
    time_stop_bars: int = 12
    breakeven_after_pct: float | None = None
    trail_start_pct: float | None = None
    trail_giveback_pct: float | None = None


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0 if b else 0.0


def load_sessions(db_path: str) -> tuple[dict, dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    stats = {}
    stats["dataset_rows"] = con.execute("select count(*) from top10_1h_training_dataset").fetchone()[0]
    stats["sessions"] = con.execute("select count(*) from top10_1h_training_sessions").fetchone()[0]
    stats["closed_sessions"] = con.execute("select count(*) from top10_1h_training_sessions where is_active=0").fetchone()[0]
    stats["active_sessions"] = con.execute("select count(*) from top10_1h_training_sessions where is_active=1").fetchone()[0]
    stats["candles"] = con.execute("select count(*) from top10_1h_training_candles").fetchone()[0]
    tr = con.execute("select min(ts_iso), max(ts_iso), count(distinct inst_id) from top10_1h_training_dataset").fetchone()
    stats["min_ts_iso"], stats["max_ts_iso"], stats["insts"] = tr[0], tr[1], tr[2]

    sessions: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in con.execute(
        """
        select * from top10_1h_training_dataset
        where open is not null and high is not null and low is not null and close is not null
        order by session_id, bar_index_from_entry, ts_ms
        """
    ):
        sessions[int(row["session_id"])].append(row)
    return stats, dict(sessions)


def entry_ok(rows: list[sqlite3.Row], rule: EntryRule) -> tuple[bool, int, float, str]:
    if len(rows) <= rule.delay_bars:
        return False, -1, 0.0, "not_enough_bars"
    first = rows[0]
    idx = rule.delay_bars
    bar = rows[idx]
    entry_rank = int(first["entry_rank_1h"] or 99)
    entry_chg = float(first["entry_change_1h_pct"] or 0.0)
    if entry_rank > rule.max_entry_rank:
        return False, idx, 0.0, "entry_rank"
    if not (rule.min_entry_change <= entry_chg <= rule.max_entry_change):
        return False, idx, 0.0, "entry_change"
    if rule.require_green_confirm and not (float(bar["close"]) > float(bar["open"])):
        return False, idx, 0.0, "not_green"
    if rule.reclaim_entry_price and not (float(bar["close"]) >= float(first["entry_price"] or rows[0]["close"])):
        return False, idx, 0.0, "no_reclaim"
    if rule.max_upper_wick_pct is not None:
        high, close, open_ = float(bar["high"]), float(bar["close"]), float(bar["open"])
        body_top = max(open_, close)
        upper = pct(high, body_top) if body_top else 0.0
        if upper > rule.max_upper_wick_pct:
            return False, idx, 0.0, "upper_wick"
    if rule.min_vol_ratio is not None and idx > 0:
        prev_vols = [float(r["vol_ccy"] or 0.0) for r in rows[:idx]]
        base = sum(prev_vols) / len(prev_vols) if prev_vols else 0.0
        if base <= 0 or float(bar["vol_ccy"] or 0.0) / base < rule.min_vol_ratio:
            return False, idx, 0.0, "vol_ratio"
    return True, idx, float(bar["close"]), "ok"


def simulate_exit(rows: list[sqlite3.Row], entry_idx: int, entry_price: float, rule: ExitRule) -> tuple[float, str, int]:
    stop = entry_price * (1.0 - rule.sl_pct / 100.0)
    peak = entry_price
    max_bars = min(len(rows) - 1, entry_idx + rule.time_stop_bars)
    for i in range(entry_idx + 1, max_bars + 1):
        r = rows[i]
        high, low, close = float(r["high"]), float(r["low"]), float(r["close"])
        peak = max(peak, high)
        # conservative same-bar ordering: stop before TP/trail.
        active_stop = stop
        if rule.breakeven_after_pct is not None and pct(peak, entry_price) >= rule.breakeven_after_pct:
            active_stop = max(active_stop, entry_price)
        if rule.trail_start_pct is not None and pct(peak, entry_price) >= rule.trail_start_pct:
            trail_stop = peak * (1.0 - (rule.trail_giveback_pct or 0.0) / 100.0)
            active_stop = max(active_stop, trail_stop)
        if low <= active_stop:
            return pct(active_stop, entry_price), "stop_or_trail", i - entry_idx
        if rule.tp_pct is not None and high >= entry_price * (1.0 + rule.tp_pct / 100.0):
            return rule.tp_pct, "tp", i - entry_idx
    if max_bars > entry_idx:
        close = float(rows[max_bars]["close"])
        return pct(close, entry_price), "time_stop" if max_bars == entry_idx + rule.time_stop_bars else "session_end", max_bars - entry_idx
    return 0.0, "no_exit_bar", 0


def max_drawdown_proxy(returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


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
        "entries": len(trades),
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "avg_return": (sum(gross) / len(gross)) if gross else 0.0,
        "median_return": median(gross) if gross else 0.0,
        "net_avg_return": (sum(net) / len(net)) if net else 0.0,
        "profit_factor": (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0),
        "max_loss": min(net) if net else 0.0,
        "max_drawdown_proxy": max_drawdown_proxy(net),
        "exit_reason_counts": dict(Counter(t["exit_reason"] for t in trades)),
    }


def build_rules() -> tuple[list[EntryRule], list[ExitRule]]:
    entries = []
    for delay in [0, 1, 2, 3]:
        for max_rank in [3, 5, 10]:
            for lo, hi in [(1, 5), (2, 8), (3, 10), (5, 15), (1, 12)]:
                entries.append(EntryRule(f"delay{delay}_rank{max_rank}_chg{lo}-{hi}", delay, max_rank, lo, hi))
                if delay >= 1:
                    entries.append(EntryRule(f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_reclaim", delay, max_rank, lo, hi, True, 0.8, None, True))
                    entries.append(EntryRule(f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol", delay, max_rank, lo, hi, True, 1.2, 1.5, False))
    exits = []
    for sl in [0.8, 1.0, 1.2, 1.5, 2.0]:
        for tp in [0.6, 0.9, 1.2, 1.8, None]:
            for bars in [6, 8, 12, 18]:
                if tp is not None:
                    exits.append(ExitRule(f"sl{sl}_tp{tp}_t{bars}", sl, tp, bars))
                exits.append(ExitRule(f"sl{sl}_be0.6_trail0.9x0.4_t{bars}", sl, None, bars, 0.6, 0.9, 0.4))
                exits.append(ExitRule(f"sl{sl}_be0.8_trail1.2x0.6_t{bars}", sl, None, bars, 0.8, 1.2, 0.6))
    # de-dupe by name
    exits = list({e.name: e for e in exits}.values())
    return entries, exits


def run(db_path: str, min_trades: int, top_n: int) -> dict:
    stats, sessions = load_sessions(db_path)
    entries, exits = build_rules()
    results = []
    for er in entries:
        entry_points = []
        for sid, rows in sessions.items():
            if int(rows[0]["is_active"] or 0) != 0:
                continue
            ok, idx, price, _ = entry_ok(rows, er)
            if ok and price > 0:
                entry_points.append((sid, rows, idx, price))
        if not entry_points:
            continue
        for xr in exits:
            trades = []
            for sid, rows, idx, price in entry_points:
                ret, reason, bars = simulate_exit(rows, idx, price, xr)
                # A closed Top10 session can still have only the entry bar if it
                # left the leaderboard before the next 5m candle was collected.
                # Do not count those as closed strategy trades because no exit
                # price was observable after entry.
                if reason == "no_exit_bar":
                    continue
                trades.append({"session_id": sid, "gross_return_pct": ret, "exit_reason": reason, "bars_held": bars})
            if len(trades) >= min_trades:
                results.append(summarize(trades, er, xr))
    def rank_key(r):
        # Primary: positive net expectancy, then PF, controlled max loss, sample size, win rate.
        return (
            r["net_avg_return"],
            min(r["profit_factor"], 20),
            r["max_loss"],
            math.log(max(r["closed_trades"], 1)),
            r["win_rate"],
        )
    results.sort(key=rank_key, reverse=True)
    return {"db_stats": stats, "round_trip_cost_pct": ROUND_TRIP_COST_PCT, "min_trades": min_trades, "result_count": len(results), "top": results[:top_n]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/okx_micro_5m_tracking.sqlite")
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json-out", default="tmp_top10_training_optimizer_results.json")
    ap.add_argument("--csv-out", default="tmp_top10_training_optimizer_results.csv")
    args = ap.parse_args()
    out = run(args.db, args.min_trades, args.top)
    Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        fields = ["rank", "entry_name", "exit_name", "entries", "closed_trades", "win_rate", "avg_return", "median_return", "net_avg_return", "profit_factor", "max_loss", "max_drawdown_proxy", "exit_reason_counts"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(out["top"], 1):
            w.writerow({
                "rank": i,
                "entry_name": r["entry"]["name"],
                "exit_name": r["exit"]["name"],
                "entries": r["entries"],
                "closed_trades": r["closed_trades"],
                "win_rate": f'{r["win_rate"]:.4f}',
                "avg_return": f'{r["avg_return"]:.6f}',
                "median_return": f'{r["median_return"]:.6f}',
                "net_avg_return": f'{r["net_avg_return"]:.6f}',
                "profit_factor": f'{r["profit_factor"]:.6f}',
                "max_loss": f'{r["max_loss"]:.6f}',
                "max_drawdown_proxy": f'{r["max_drawdown_proxy"]:.6f}',
                "exit_reason_counts": json.dumps(r["exit_reason_counts"], ensure_ascii=False, sort_keys=True),
            })
    print(json.dumps({"db_stats": out["db_stats"], "round_trip_cost_pct": out["round_trip_cost_pct"], "result_count": out["result_count"], "top": out["top"][:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
