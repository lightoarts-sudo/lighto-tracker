#!/usr/bin/env python3
"""Single-factor IC analysis for OKX 1H Top10 strategies.

Tests each candidate factor's predictive power for forward returns.
Uses only data available in top10_1h_training_dataset + sessions (no external joins needed).
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median, stdev
from typing import Callable

DB_PATH = "data/okx_micro_5m_tracking.sqlite"
ROUND_TRIP_COST = 0.16

# ----------------------------------------------------------------------
# Factor definitions: each returns a float per session (at entry bar)
# All computed from dataset/sessions tables only
# ----------------------------------------------------------------------


@dataclass
class Factor:
    name: str
    desc: str
    func: Callable[[sqlite3.Row, list[sqlite3.Row]], float | None]


# --- Session-level factors (computed from full session candle history) ---

def f_rank_improve(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Rank improvement so far: entry_rank - best_rank_so_far (min rank up to entry bar)."""
    entry_rank = row["entry_rank_1h"]
    # At entry bar (index 0), min_rank_so_far = entry_rank
    # But we can use min_rank_1h from session (pre-computed extreme)
    min_rank = row["min_rank_1h"]
    if min_rank is None:
        return None
    return float(entry_rank - min_rank)


def f_chg_persistence(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Current change% / entry change%. <1 = decay, >1 = acceleration."""
    entry_chg = row["entry_change_1h_pct"]
    cur_chg = row["change_1h_pct"]
    if entry_chg == 0:
        return None
    return cur_chg / entry_chg


def f_vol_trend(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Volume trend: avg last 3 bars / avg last 10 bars (up to current bar)."""
    idx = row["bar_index_from_entry"]
    if idx < 2:
        return None
    recent = [float(b["vol_ccy"] or 0) for b in bars[max(0, idx-2):idx+1]]
    lookback = [float(b["vol_ccy"] or 0) for b in bars[max(0, idx-9):idx+1]]
    if not lookback or sum(lookback) == 0:
        return None
    return (sum(recent)/len(recent)) / (sum(lookback)/len(lookback))


def f_body_ratio(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Average body/range ratio of last 3 bars (conviction)."""
    idx = row["bar_index_from_entry"]
    if idx < 0:
        return None
    ratios = []
    for i in range(max(0, idx-2), idx+1):
        b = bars[i]
        rng = b["high"] - b["low"]
        if rng == 0:
            continue
        body = abs(b["close"] - b["open"])
        ratios.append(body / rng)
    return sum(ratios) / len(ratios) if ratios else None


def f_consecutive_green(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Count of consecutive green bars up to entry (momentum persistence)."""
    count = 0
    for b in bars[:row["bar_index_from_entry"]+1]:
        if b["close"] > b["open"]:
            count += 1
        else:
            count = 0
    return float(count)


def f_rank_momentum(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Rank momentum: entry_rank - current_rank (positive = improving)."""
    entry_rank = row["entry_rank_1h"]
    cur_rank = row["rank_1h"]
    if cur_rank is None:
        return None
    return float(entry_rank - cur_rank)


def f_change_momentum(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Change% momentum: current_change - entry_change (positive = accelerating)."""
    return row["change_1h_pct"] - row["entry_change_1h_pct"]


def f_session_duration(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Session duration in bars (proxy for trend maturity)."""
    return float(row["candle_count"])


def f_time_of_day(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Hour of day (0-23) at entry - regime proxy."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(row["entered_at"].replace("Z", "+00:00"))
        return float(dt.hour)
    except Exception:
        return None


def f_entry_rank(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Entry rank (1-10). Lower = stronger."""
    return float(row["entry_rank_1h"])


def f_entry_change(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Entry change_1h_pct. Higher = stronger momentum."""
    return row["entry_change_1h_pct"]


def f_max_chg_so_far(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Max change% achieved in session so far (at entry bar = entry_change)."""
    return row["max_change_1h_pct"]


def f_unrealized_pnl(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Unrealized P&L at entry bar (should be ~0)."""
    return row["return_from_entry_pct"]


# --- Advanced: compute from full session candles (need bars beyond entry) ---
# These use the full session history to compute "regime" measures at entry time

def f_atr_session(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Session ATR% (using all bars up to entry). At entry bar only 1 bar, so use next few bars as proxy."""
    # For entry bar (index 0), we don't have history. Use session-level max_change as volatility proxy.
    max_chg = row["max_change_1h_pct"]
    entry_chg = row["entry_change_1h_pct"]
    if max_chg is None or entry_chg is None:
        return None
    return max_chg - entry_chg  # Range from entry to max as vol proxy


def f_dist_to_session_high(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Distance from entry price to session high (max_change proxy)."""
    max_chg = row["max_change_1h_pct"]
    entry_chg = row["entry_change_1h_pct"]
    if max_chg is None or entry_chg is None:
        return None
    return max_chg - entry_chg  # How much more upside from entry to session peak


def f_dist_to_session_low(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Distance from entry to session low (via min_rank proxy). Not directly available, skip."""
    return None


# --- Momentum quality factors ---

def f_chg_acceleration(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Change acceleration: (change@bar1 - change@bar0) if available."""
    idx = row["bar_index_from_entry"]
    if idx == 0 and len(bars) > 1:
        return bars[1]["change_1h_pct"] - bars[0]["change_1h_pct"]
    return None


def f_rank_acceleration(row: sqlite3.Row, bars: list[sqlite3.Row]) -> float | None:
    """Rank acceleration: (rank@bar0 - rank@bar1) if available (positive = improving)."""
    idx = row["bar_index_from_entry"]
    if idx == 0 and len(bars) > 1:
        r0 = bars[0]["rank_1h"]
        r1 = bars[1]["rank_1h"]
        if r0 is not None and r1 is not None:
            return float(r0 - r1)
    return None


ALL_FACTORS = [
    # Core entry characteristics
    Factor("entry_rank", "Entry rank (1-10, lower better)", f_entry_rank),
    Factor("entry_change", "Entry 1H change% (momentum strength)", f_entry_change),
    Factor("max_chg_so_far", "Session max change% so far", f_max_chg_so_far),
    Factor("unrealized_pnl", "Unrealized P&L at entry", f_unrealized_pnl),

    # Momentum persistence / quality
    Factor("rank_improve", "Rank improvement (entry - min_rank)", f_rank_improve),
    Factor("chg_persistence", "Change% persistence (cur/entry)", f_chg_persistence),
    Factor("rank_momentum", "Rank momentum (entry - current)", f_rank_momentum),
    Factor("change_momentum", "Change% momentum (cur - entry)", f_change_momentum),
    Factor("chg_acceleration", "Change acceleration (bar1 - bar0)", f_chg_acceleration),
    Factor("rank_acceleration", "Rank acceleration (bar0 - bar1)", f_rank_acceleration),

    # Volume / conviction
    Factor("vol_trend", "Volume trend (3-bar/10-bar avg)", f_vol_trend),
    Factor("body_ratio", "Body/range ratio (last 3 bars)", f_body_ratio),
    Factor("consec_green", "Consecutive green bars count", f_consecutive_green),

    # Session context
    Factor("session_duration", "Session duration (bars)", f_session_duration),
    Factor("time_of_day", "Hour of day at entry", f_time_of_day),

    # Volatility / range proxies
    Factor("atr_session", "Session range proxy (max_chg - entry_chg)", f_atr_session),
    Factor("dist_to_high", "Distance to session high (max_chg - entry_chg)", f_dist_to_session_high),
]


# ----------------------------------------------------------------------
# Load data
# ----------------------------------------------------------------------


def load_sessions(db_path: str) -> tuple[dict, dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    stats = {}
    stats["dataset_rows"] = con.execute("select count(*) from top10_1h_training_dataset").fetchone()[0]
    stats["sessions"] = con.execute("select count(*) from top10_1h_training_sessions").fetchone()[0]
    stats["closed_sessions"] = con.execute("select count(*) from top10_1h_training_sessions where is_active=0").fetchone()[0]

    sessions: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in con.execute("""
        select d.*, s.candle_count, s.entered_at, s.exit_reason
        from top10_1h_training_dataset d
        join top10_1h_training_sessions s on d.session_id = s.id
        where s.is_active = 0
        and d.open is not null and d.high is not null and d.low is not null and d.close is not null
        order by d.session_id, d.bar_index_from_entry
    """):
        sessions[int(row["session_id"])].append(row)

    con.close()
    return stats, dict(sessions)


# ----------------------------------------------------------------------
# Forward return calculation
# ----------------------------------------------------------------------


def forward_returns(bars: list[sqlite3.Row], entry_idx: int, horizons: list[int]) -> dict[int, float]:
    """Compute gross forward returns at different horizons (in bars)."""
    entry_price = bars[entry_idx]["close"]
    rets = {}
    for h in horizons:
        target_idx = min(entry_idx + h, len(bars) - 1)
        if target_idx <= entry_idx:
            rets[h] = 0.0
            continue
        exit_price = bars[target_idx]["close"]
        rets[h] = (exit_price / entry_price - 1.0) * 100.0
    return rets


# ----------------------------------------------------------------------
# IC Analysis
# ----------------------------------------------------------------------


def spearman_rho(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation."""
    n = len(x)
    if n < 3:
        return 0.0
    # Rank transform (handle ties with average rank)
    def rank_vals(vals):
        sorted_vals = sorted(set(vals))
        rank_map = {v: i+1 for i, v in enumerate(sorted_vals)}
        return [rank_map[v] for v in vals]

    rx = rank_vals(x)
    ry = rank_vals(y)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1.0 - (6.0 * d2) / (n * (n * n - 1))


def pearson_r(x: list[float], y: list[float]) -> float:
    """Pearson correlation."""
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(x)/n, sum(y)/n
    num = sum((a-mx)*(b-my) for a,b in zip(x,y))
    den_x = math.sqrt(sum((a-mx)**2 for a in x))
    den_y = math.sqrt(sum((b-my)**2 for b in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def quantile_analysis(factor_vals: list[float], returns: list[float], q: int = 5) -> dict:
    """Split by factor quintiles, return mean return per quantile."""
    n = len(factor_vals)
    if n < q * 3:
        return {}
    idx = sorted(range(n), key=lambda i: factor_vals[i])
    bin_size = n // q
    result = {}
    for i in range(q):
        start = i * bin_size
        end = (i + 1) * bin_size if i < q - 1 else n
        sel = idx[start:end]
        if sel:
            result[f"Q{i+1}"] = sum(returns[j] for j in sel) / len(sel)
    return result


def analyze_factor(factor: Factor, sessions: dict, horizons: list[int]) -> dict:
    """Run IC analysis for one factor across all horizons."""
    results = {"factor": factor.name, "desc": factor.desc, "horizons": {}}

    for h in horizons:
        factor_vals = []
        fwd_rets = []

        for sid, bars in sessions.items():
            entry_bar = next((b for b in bars if b["bar_index_from_entry"] == 0), None)
            if not entry_bar:
                continue

            fval = factor.func(entry_bar, bars)
            if fval is None:
                continue

            rets = forward_returns(bars, 0, [h])
            factor_vals.append(fval)
            fwd_rets.append(rets[h])

        if len(factor_vals) < 30:
            results["horizons"][f"{h}b"] = {"n": len(factor_vals), "error": "insufficient samples"}
            continue

        net_rets = [r - ROUND_TRIP_COST for r in fwd_rets]

        spearman = spearman_rho(factor_vals, net_rets)
        pearson = pearson_r(factor_vals, net_rets)
        quantiles = quantile_analysis(factor_vals, net_rets, 5)

        # Monotonic: Q1 <= Q2 <= Q3 <= Q4 <= Q5 (for positive IC) or reverse (for negative IC)
        mono = False
        if quantiles:
            q_vals = [quantiles.get(f"Q{i}", 0) for i in range(1, 6)]
            increasing = all(q_vals[i] <= q_vals[i+1] for i in range(4))
            decreasing = all(q_vals[i] >= q_vals[i+1] for i in range(4))
            mono = increasing or decreasing

        results["horizons"][f"{h}b"] = {
            "n": len(factor_vals),
            "spearman_ic": round(spearman, 4),
            "pearson_ic": round(pearson, 4),
            "mean_return": round(sum(net_rets)/len(net_rets), 4),
            "quantile_returns": {k: round(v, 4) for k, v in quantiles.items()},
            "monotonic": mono,
            "ic_sign": "positive" if spearman > 0 else "negative",
        }

    return results


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main():
    print(f"Loading data from {DB_PATH}...")
    stats, sessions = load_sessions(DB_PATH)
    print(f"  Sessions: {stats['sessions']}, Closed: {stats['closed_sessions']}")

    horizons = [6, 8, 12, 18]

    print(f"\nAnalyzing {len(ALL_FACTORS)} factors across horizons {horizons}...")
    all_results = []

    for factor in ALL_FACTORS:
        print(f"  {factor.name}...", end=" ", flush=True)
        res = analyze_factor(factor, sessions, horizons)
        all_results.append(res)
        best_h = max(res["horizons"].keys(), key=lambda k: abs(res["horizons"][k].get("spearman_ic", 0)))
        best_ic = res["horizons"][best_h].get("spearman_ic", 0)
        print(f"best IC={best_ic:.4f} @ {best_h}")

    # Save detailed results
    out_path = Path("factor_ic_results.json")
    out_path.write_text(json.dumps({
        "db_stats": stats,
        "horizons": horizons,
        "round_trip_cost": ROUND_TRIP_COST,
        "factors": all_results
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detailed results to {out_path}")

    # Print summary table
    print("\n" + "=" * 110)
    print(f"{'Factor':<22} {'Desc':<38} {'Best H':<8} {'Spearman':<10} {'Pearson':<10} {'Mono':<6} {'Sign':<10} {'N':<6}")
    print("-" * 110)

    for res in all_results:
        best_h = max(res["horizons"].keys(), key=lambda k: abs(res["horizons"][k].get("spearman_ic", 0)))
        hdata = res["horizons"][best_h]
        mono = "✓" if hdata.get("monotonic") else "✗"
        sign = hdata.get("ic_sign", "")
        print(f"{res['factor']:<22} {res['desc']:<38} {best_h:<8} {hdata.get('spearman_ic',0):<10.4f} {hdata.get('pearson_ic',0):<10.4f} {mono:<6} {sign:<10} {hdata.get('n',0):<6}")

    # Top factors by avg |IC| across horizons
    print("\n" + "=" * 110)
    print("RANKED BY AVERAGE |SPEARMAN IC| ACROSS HORIZONS:")
    print("-" * 110)

    factor_scores = []
    for res in all_results:
        ics = [abs(h.get("spearman_ic", 0)) for h in res["horizons"].values() if "spearman_ic" in h]
        avg_ic = sum(ics)/len(ics) if ics else 0
        factor_scores.append((res["factor"], res["desc"], avg_ic, ics))

    factor_scores.sort(key=lambda x: x[2], reverse=True)
    for i, (name, desc, avg, ics) in enumerate(factor_scores, 1):
        print(f"  {i:2d}. {name:<22} {desc:<38} avg|IC|={avg:.4f}  [{', '.join(f'{ic:.4f}' for ic in ics)}]")

    # Detailed quantile analysis for top factors
    print("\n" + "=" * 110)
    print("QUINTILE ANALYSIS (Top 5 factors @ 12b horizon):")
    print("-" * 110)

    top5 = factor_scores[:5]
    for name, desc, avg, _ in top5:
        res = next(r for r in all_results if r["factor"] == name)
        hdata = res["horizons"].get("12b", {})
        qrets = hdata.get("quantile_returns", {})
        if qrets:
            q_str = " | ".join(f"Q{i}: {qrets.get(f'Q{i}',0):+.4f}%" for i in range(1, 6))
            print(f"  {name:<22}: {q_str}  (spread Q5-Q1: {qrets.get('Q5',0)-qrets.get('Q1',0):+.4f}%)")

    # Recommendation
    print("\n" + "=" * 110)
    print("RECOMMENDATION FOR OPTIMIZER:")
    print("-" * 110)

    strong = [f for f in factor_scores if f[2] > 0.02]
    moderate = [f for f in factor_scores if 0.01 < f[2] <= 0.02]
    weak = [f for f in factor_scores if f[2] <= 0.01]

    if strong:
        print("  STRONG (avg|IC| > 0.02) - HIGH PRIORITY:")
        for f in strong:
            print(f"    + {f[0]}: {f[1]} (avg|IC|={f[2]:.4f})")

    if moderate:
        print("\n  MODERATE (0.01 - 0.02) - CONSIDER:")
        for f in moderate:
            print(f"    ~ {f[0]}: {f[1]} (avg|IC|={f[2]:.4f})")

    if weak:
        print("\n  WEAK (≤ 0.01) - SKIP:")
        for f in weak:
            print(f"    - {f[0]}: {f[1]} (avg|IC|={f[2]:.4f})")

    print("\n  Suggested factor set for optimizer (top 6):")
    for f in strong[:6]:
        print(f"    {f[0]}")


if __name__ == "__main__":
    main()