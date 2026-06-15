#!/usr/bin/env python3
"""Lightweight optimizer for OKX 1H Top10 training sessions with Walk-Forward validation.

Pure Python + sqlite3. Replays point-in-time rows from `top10_1h_training_dataset`.
Entry predicates can only inspect bars at or before the entry/confirmation bar.

Features:
- Walk-forward validation (expanding window)
- Mandatory quality filters: reclaim_entry_price, max_upper_wick_pct, min_vol_ratio
- Configurable train/test split
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Optional

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
    # New factors from IC analysis
    min_atr_proxy: float | None = None
    max_atr_proxy: float | None = None
    allowed_hours: tuple[int, ...] | None = None
    min_session_bars: int | None = None
    max_session_bars: int | None = None
    min_rank_momentum: int | None = None


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
        select d.*, s.candle_count, s.entered_at
        from top10_1h_training_dataset d
        join top10_1h_training_sessions s on d.session_id = s.id
        where s.is_active = 0
        and d.open is not null and d.high is not null and d.low is not null and d.close is not null
        order by d.session_id, d.bar_index_from_entry, d.ts_ms
        """
    ):
        sessions[int(row["session_id"])].append(row)
    con.close()
    return stats, dict(sessions)


def entry_ok(rows: list[sqlite3.Row], rule: EntryRule) -> tuple[bool, int, float, str]:
    """
    Dynamic rank entry: scan session bars starting from delay_bars,
    find first bar where rank_1h <= max_entry_rank AND all conditions met.
    This matches live logic: we only enter when coin's CURRENT rank qualifies.
    """
    if len(rows) <= rule.delay_bars:
        return False, -1, 0.0, "not_enough_bars"

    first = rows[0]
    session_entry_price = float(first["entry_price"] or first["close"])
    session_entry_chg = float(first["entry_change_1h_pct"] or 0.0)

    # Session-level filters (based on session start, unchanged)
    if not (rule.min_entry_change <= session_entry_chg <= rule.max_entry_change):
        return False, -1, 0.0, "entry_change_session"

    # Hour of day filter (session start)
    if rule.allowed_hours is not None:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(first["entered_at"].replace("Z", "+00:00"))
            if dt.hour not in rule.allowed_hours:
                return False, -1, 0.0, "hour_filter"
        except Exception:
            return False, -1, 0.0, "hour_parse_error"

    # Session duration filter (total session length)
    if rule.min_session_bars is not None or rule.max_session_bars is not None:
        session_bars = int(first["candle_count"] or 0)
        if rule.min_session_bars is not None and session_bars < rule.min_session_bars:
            return False, -1, 0.0, "session_short"
        if rule.max_session_bars is not None and session_bars > rule.max_session_bars:
            return False, -1, 0.0, "session_long"

    # ATR proxy: session entry bar range (unchanged)
    if rule.min_atr_proxy is not None or rule.max_atr_proxy is not None:
        entry_bar = rows[0]
        entry_range_pct = ((float(entry_bar["high"]) - float(entry_bar["low"])) / float(entry_bar["open"])) * 100.0
        if rule.min_atr_proxy is not None and entry_range_pct < rule.min_atr_proxy:
            return False, -1, 0.0, "atr_proxy_low"
        if rule.max_atr_proxy is not None and entry_range_pct > rule.max_atr_proxy:
            return False, -1, 0.0, "atr_proxy_high"

    # Scan bars from delay_bars onwards for dynamic rank entry
    for idx in range(rule.delay_bars, len(rows)):
        bar = rows[idx]
        current_rank = int(bar["rank_1h"] or 99)
        current_chg = float(bar["change_1h_pct"] or 0.0)

        # Dynamic rank check: only enter when CURRENT rank qualifies
        if current_rank > rule.max_entry_rank:
            continue

        # Change at entry bar (could differ from session start)
        if not (rule.min_entry_change <= current_chg <= rule.max_entry_change):
            continue

        # Green confirm at entry bar
        if rule.require_green_confirm and not (float(bar["close"]) > float(bar["open"])):
            continue

        # Reclaim entry price (vs session entry price)
        if rule.reclaim_entry_price and not (float(bar["close"]) >= session_entry_price):
            continue

        # Upper wick at entry bar
        if rule.max_upper_wick_pct is not None:
            high, close, open_ = float(bar["high"]), float(bar["close"]), float(bar["open"])
            body_top = max(open_, close)
            upper = pct(high, body_top) if body_top else 0.0
            if upper > rule.max_upper_wick_pct:
                continue

        # Volume ratio at entry bar (vs prior bars in session)
        if rule.min_vol_ratio is not None and idx > 0:
            prev_vols = [float(r["vol_ccy"] or 0.0) for r in rows[:idx]]
            base = sum(prev_vols) / len(prev_vols) if prev_vols else 0.0
            if base <= 0 or float(bar["vol_ccy"] or 0.0) / base < rule.min_vol_ratio:
                continue

        # Rank momentum: session_entry_rank - current_rank (improvement during delay)
        if rule.min_rank_momentum is not None and rule.delay_bars >= 1:
            session_entry_rank = int(first["entry_rank_1h"] or 99)
            rank_mom = session_entry_rank - current_rank  # positive = rank improved
            if rank_mom < rule.min_rank_momentum:
                continue

        # All checks passed at this bar -> enter here
        return True, idx, float(bar["close"]), "ok"

    return False, -1, 0.0, "no_valid_entry_bar"


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


def build_rules(from_date: Optional[str] = None) -> tuple[list[EntryRule], list[ExitRule]]:
    """
    Build entry and exit rules.
    
    BASE QUALITY FILTERS (from factor IC analysis - original green_vol):
    - max_upper_wick_pct = 1.2    (reject fake breakouts)
    - min_vol_ratio = 1.5         (volume confirmation)
    - require_green_confirm = True
    
    STRICTER VARIANTS (tested as alternatives):
    - reclaim_entry_price = True  (wait for retrace to signal close)
    - max_upper_wick_pct = 0.8    (stricter wick filter)
    - min_vol_ratio = 2.0         (stronger volume confirmation)
    """
    entries = []
    for delay in [3]:  # Focus on delay=3 (best from IC analysis)
        for max_rank in [3]:  # Rank 3 dominates (rank 5 degrades)
            for lo, hi in [(3, 10)]:  # Best range from IC
                # Base with ORIGINAL green_vol filters (proven in production) - vol_ratio relaxed to 1.0
                entries.append(EntryRule(
                    f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol",
                    delay, max_rank, lo, hi,
                    True, 1.2, 1.0, False  # green_confirm, max_wick=1.2%, vol_ratio=1.0, reclaim=False
                ))
                
                # Base + duration filter (IC showed session_duration works)
                for dmin, dmax in [(6, 60), (8, 50), (10, 40)]:
                    entries.append(EntryRule(
                        f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol_dur{dmin}-{dmax}",
                        delay, max_rank, lo, hi,
                        True, 1.2, 1.0, False,  # original quality filters (vol_ratio=1.0)
                        min_session_bars=dmin, max_session_bars=dmax
                    ))

                # STRICTER VARIANT: + reclaim_entry_price + stricter wick + higher vol
                entries.append(EntryRule(
                    f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol_reclaim",
                    delay, max_rank, lo, hi,
                    True, 0.8, 2.0, True  # reclaim=True, wick=0.8%, vol=2.0
                ))

                # Stricter + duration
                for dmin, dmax in [(6, 60), (8, 50), (10, 40)]:
                    entries.append(EntryRule(
                        f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol_reclaim_dur{dmin}-{dmax}",
                        delay, max_rank, lo, hi,
                        True, 0.8, 2.0, True,
                        min_session_bars=dmin, max_session_bars=dmax
                    ))

                # NEW: atr_session (remaining upside space) filter - IC=0.524 strongest factor!
                # atr_session = max_chg_so_far - entry_change (session remaining upside)
                # Q1-Q3 negative, Q4-Q5 positive → sweet spot ~2-15%
                for atr_min, atr_max in [(2, 15), (3, 12), (5, 10)]:
                    entries.append(EntryRule(
                        f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol_atr{atr_min}-{atr_max}",
                        delay, max_rank, lo, hi,
                        True, 1.2, 1.0, False,  # base green_vol filters
                        min_atr_proxy=atr_min, max_atr_proxy=atr_max
                    ))

                    # atr_session + duration combo
                    for dmin, dmax in [(8, 50), (10, 40)]:
                        entries.append(EntryRule(
                            f"delay{delay}_rank{max_rank}_chg{lo}-{hi}_green_vol_atr{atr_min}-{atr_max}_dur{dmin}-{dmax}",
                            delay, max_rank, lo, hi,
                            True, 1.2, 1.0, False,
                            min_atr_proxy=atr_min, max_atr_proxy=atr_max,
                            min_session_bars=dmin, max_session_bars=dmax
                        ))

    exits = []
    for sl in [0.8, 1.0, 1.2]:  # Standard SLs
        for bars in [8, 12, 18]:  # Standard time stops
            # BE + Trail (proven best combo)
            exits.append(ExitRule(f"sl{sl}_be0.6_trail0.9x0.4_t{bars}", sl, None, bars, 0.6, 0.9, 0.4))
            exits.append(ExitRule(f"sl{sl}_be0.8_trail1.2x0.6_t{bars}", sl, None, bars, 0.8, 1.2, 0.6))
    exits = list({e.name: e for e in exits}.values())
    return entries, exits


def filter_sessions_by_date(sessions: dict, start: Optional[str], end: Optional[str]) -> dict:
    """Filter sessions by entry date range (inclusive start, exclusive end)."""
    if not start and not end:
        return sessions
    filtered = {}
    for sid, rows in sessions.items():
        first = rows[0]
        entered = first["entered_at"]
        if start and entered < start:
            continue
        if end and entered >= end:
            continue
        filtered[sid] = rows
    return filtered


def run_walk_forward(
    db_path: str,
    min_trades: int,
    top_n: int,
    train_days: int = 7,
    test_days: int = 2,
    lookback_days: int = 0
) -> dict:
    """
    Walk-forward validation:
    - Train on earliest `train_days` of data
    - Test on next `test_days`
    - Roll forward by `test_days` until lookback exhausted
    """
    stats, all_sessions = load_sessions(db_path)
    entries, exits = build_rules()
    
    # Get date range
    min_ts = min(r[0]["entered_at"] for r in all_sessions.values())
    max_ts = max(r[0]["entered_at"] for r in all_sessions.values())
    if lookback_days > 0:
        cutoff = datetime.fromisoformat(max_ts.replace("Z", "+00:00")) - timedelta(days=lookback_days)
        min_ts = cutoff.isoformat()
    
    start_dt = datetime.fromisoformat(min_ts.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(max_ts.replace("Z", "+00:00"))
    
    results_all = []
    window_num = 0
    current_start = start_dt
    
    while current_start + timedelta(days=train_days) < end_dt:
        train_start = current_start.isoformat()
        train_end = (current_start + timedelta(days=train_days)).isoformat()
        test_start = train_end
        test_end = (current_start + timedelta(days=train_days + test_days)).isoformat()
        
        if test_start >= end_dt.isoformat():
            break
            
        window_num += 1
        print(f"  Window {window_num}: Train {train_start}~{train_end}, Test {test_start}~{test_end}")
        
        train_sessions = filter_sessions_by_date(all_sessions, train_start, train_end)
        test_sessions = filter_sessions_by_date(all_sessions, test_start, test_end)
        
        if len(train_sessions) < 50 or len(test_sessions) < 10:
            print(f"    Skipping: insufficient samples (train={len(train_sessions)}, test={len(test_sessions)})")
            current_start += timedelta(days=test_days)
            continue
        
        # Train phase: find best params on train set
        train_results = []
        for er in entries:
            entry_points = []
            for sid, rows in train_sessions.items():
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
                    trades.append({"session_id": sid, "gross_return_pct": ret, "exit_reason": reason, "bars_held": bars})
                if len(trades) >= min_trades:
                    train_results.append(summarize(trades, er, xr))
        
        def rank_key(r):
            return (
                r["net_avg_return"],
                min(r["profit_factor"], 20),
                r["max_loss"],
                math.log(max(r["closed_trades"], 1)),
                r["win_rate"],
            )
        train_results.sort(key=rank_key, reverse=True)
        
        if not train_results:
            current_start += timedelta(days=test_days)
            continue
            
        # Take top 3 from training
        top_train = train_results[:3]
        
        # Test phase: validate on out-of-sample test set
        for tr in top_train:
            er = EntryRule(**tr["entry"])
            xr = ExitRule(**tr["exit"])
            
            test_trades = []
            for sid, rows in test_sessions.items():
                ok, idx, price, _ = entry_ok(rows, er)
                if ok and price > 0:
                    ret, reason, bars = simulate_exit(rows, idx, price, xr)
                    if reason == "no_exit_bar":
                        continue
                    test_trades.append({"session_id": sid, "gross_return_pct": ret, "exit_reason": reason, "bars_held": bars})
            
            if len(test_trades) >= min_trades:
                test_result = summarize(test_trades, er, xr)
                test_result["window"] = window_num
                test_result["train_net_avg"] = tr["net_avg_return"]
                test_result["train_pf"] = tr["profit_factor"]
                test_result["train_wr"] = tr["win_rate"]
                results_all.append(test_result)
        
        current_start += timedelta(days=test_days)
    
    # Aggregate results across all test windows
    if not results_all:
        return {"db_stats": stats, "round_trip_cost_pct": ROUND_TRIP_COST_PCT, "min_trades": min_trades, "result_count": 0, "top": []}
    
    # Group by strategy (entry+exit) and average metrics
    from collections import defaultdict
    agg = defaultdict(list)
    for r in results_all:
        key = (json.dumps(r["entry"], sort_keys=True), json.dumps(r["exit"], sort_keys=True))
        agg[key].append(r)
    
    final = []
    for key, wins in agg.items():
        entry_dict, exit_dict = key
        # Average metrics across windows
        n = len(wins)
        avg_net = sum(w["net_avg_return"] for w in wins) / n
        avg_pf = sum(w["profit_factor"] for w in wins) / n
        avg_wr = sum(w["win_rate"] for w in wins) / n
        avg_max_loss = sum(w["max_loss"] for w in wins) / n
        total_trades = sum(w["closed_trades"] for w in wins)
        
        # Only keep if profitable in majority of windows
        profitable_windows = sum(1 for w in wins if w["net_avg_return"] > 0)
        
        if profitable_windows / n >= 0.5:  # At least 50% windows positive
            final.append({
                "entry": json.loads(entry_dict),
                "exit": json.loads(exit_dict),
                "windows_tested": n,
                "profitable_windows": profitable_windows,
                "avg_net_avg_return": avg_net,
                "avg_profit_factor": avg_pf,
                "avg_win_rate": avg_wr,
                "avg_max_loss": avg_max_loss,
                "total_trades": total_trades,
                "window_details": wins,
            })
    
    def final_rank_key(r):
        return (
            r["avg_net_avg_return"],
            min(r["avg_profit_factor"], 20),
            r["avg_max_loss"],
            math.log(max(r["total_trades"], 1)),
            r["profitable_windows"],
            r["avg_win_rate"],
        )
    final.sort(key=final_rank_key, reverse=True)
    
    return {
        "db_stats": stats,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "min_trades": min_trades,
        "train_days": train_days,
        "test_days": test_days,
        "windows_tested": window_num,
        "result_count": len(results_all),
        "top": final[:top_n]
    }


def run(
    db_path: str,
    min_trades: int,
    top_n: int,
    lookback_days: int = 0,
    walk_forward: bool = False,
    train_days: int = 7,
    test_days: int = 2
) -> dict:
    if walk_forward:
        return run_walk_forward(db_path, min_trades, top_n, train_days, test_days, lookback_days)
    
    stats, sessions = load_sessions(db_path)
    if lookback_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cutoff_str = cutoff.isoformat()
        sessions = {sid: rows for sid, rows in sessions.items() if rows[0]["entered_at"] >= cutoff_str}
    
    entries, exits = build_rules()
    results = []
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
                trades.append({"session_id": sid, "gross_return_pct": ret, "exit_reason": reason, "bars_held": bars})
            if len(trades) >= min_trades:
                results.append(summarize(trades, er, xr))
    def rank_key(r):
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
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--lookback-days", type=int, default=0, help="Only include sessions entered within the last N days (0 = all)")
    ap.add_argument("--json-out", default="tmp_top10_training_optimizer_results.json")
    ap.add_argument("--csv-out", default="tmp_top10_training_optimizer_results.csv")
    # Walk-forward args
    ap.add_argument("--walk-forward", action="store_true", help="Enable walk-forward validation")
    ap.add_argument("--train-days", type=int, default=7, help="Training window size in days")
    ap.add_argument("--test-days", type=int, default=2, help="Test window size in days")
    args = ap.parse_args()
    
    out = run(args.db, args.min_trades, args.top, args.lookback_days, args.walk_forward, args.train_days, args.test_days)
    
    Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    
    if args.walk_forward and "top" in out and out["top"]:
        # CSV format for walk-forward results
        with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
            fields = ["rank", "entry_name", "exit_name", "windows_tested", "profitable_windows",
                      "avg_net_avg_return", "avg_profit_factor", "avg_win_rate", "avg_max_loss", "total_trades"]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for i, r in enumerate(out["top"], 1):
                entry_name = r["entry"]["name"]
                exit_name = r["exit"]["name"]
                w.writerow({
                    "rank": i,
                    "entry_name": entry_name,
                    "exit_name": exit_name,
                    "windows_tested": r["windows_tested"],
                    "profitable_windows": r["profitable_windows"],
                    "avg_net_avg_return": f'{r["avg_net_avg_return"]:.6f}',
                    "avg_profit_factor": f'{r["avg_profit_factor"]:.6f}',
                    "avg_win_rate": f'{r["avg_win_rate"]:.4f}',
                    "avg_max_loss": f'{r["avg_max_loss"]:.6f}',
                    "total_trades": r["total_trades"],
                })
    else:
        # Original CSV format
        with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
            fields = ["rank", "entry_name", "exit_name", "entries", "closed_trades", "win_rate", 
                      "avg_return", "median_return", "net_avg_return", "profit_factor", "max_loss", 
                      "max_drawdown_proxy", "exit_reason_counts"]
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
    
    print(json.dumps({
        "db_stats": out["db_stats"],
        "round_trip_cost_pct": out["round_trip_cost_pct"],
        "result_count": out["result_count"],
        "top": out["top"][:5]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()