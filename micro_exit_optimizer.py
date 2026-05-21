#!/usr/bin/env python3
"""Brute-force exit-parameter optimizer for LIGHTOARTS OKX micro strategy.

Uses only the Python standard library so it works in the current lightweight
Render/local environment where pandas/vectorbt are not installed. It reuses the
same enriched 5m rows produced by okx_micro_report_job.py and sweeps TP/SL /
breakeven / trailing / time-stop combinations.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class ExitParams:
    sl: float = 1.0
    tp1: float = 1.0
    tp2: float = 2.0
    be: float = 0.2
    trail_start: float = 2.0
    trail_giveback: float = 1.0
    time_stop_bars: int = 6


DEFAULT_GRID = {
    "sl": [0.8, 1.0, 1.2],
    "tp1": [0.8, 1.0, 1.2],
    "tp2": [1.8, 2.0, 2.5, 3.0],
    "be": [0.0, 0.2, 0.3],
    "trail_start": [1.8, 2.0, 2.5],
    "trail_giveback": [0.6, 0.8, 1.0, 1.2],
    "time_stop_bars": [3, 6, 9],
}


def should_enter(rows: Sequence[dict], i: int) -> bool:
    r = rows[i]
    prev = rows[i - 1]
    ret1 = (r["close"] / rows[i - 12]["close"] - 1) * 100
    ret12 = (r["close"] / rows[0]["close"] - 1) * 100
    breakout = (
        r["close"] > prev["high12_prev"]
        and r["ema9"] > r["ema21"]
        and ret1 > 0.35
        and ret12 > 0
        and r["vol_ratio"] >= 1.15
    )
    pullback = (
        prev["low"] <= prev["ema21"] * 1.003
        and r["close"] > r["open"]
        and r["close"] > r["ema9"] > r["ema21"]
        and ret1 > 0.1
    )
    return breakout or pullback


def simulate_trades(enriched: Dict[str, List[dict]], watch: Sequence[str], params: ExitParams) -> List[dict]:
    trades: List[dict] = []
    for inst in watch:
        rows = enriched.get(inst)
        if not rows or len(rows) < 26:
            continue
        inpos = False
        entry = 0.0
        entry_i = 0
        stop = 0.0
        remaining = 1.0
        realized_pct = 0.0
        tp1 = False
        peak = 0.0
        for i in range(25, len(rows)):
            r = rows[i]
            if not inpos:
                if should_enter(rows, i):
                    inpos = True
                    entry = r["close"]
                    entry_i = i
                    structural_stop = min(r["ema21"], r["low12_prev"]) * 0.998
                    hard_stop = entry * (1 - params.sl / 100)
                    stop = max(structural_stop, hard_stop)
                    remaining = 1.0
                    realized_pct = 0.0
                    tp1 = False
                    peak = entry
                continue

            peak = max(peak, r["high"])
            pnl = (r["close"] / entry - 1) * 100
            reason = None
            xp = None
            breakeven_stop = entry * (1 + params.be / 100)
            giveback = ((peak - r["close"]) / peak) * 100 if peak else 0.0
            peak_gain = ((peak - entry) / entry) * 100 if entry else 0.0

            if r["low"] <= stop:
                reason = "SL"
                xp = realized_pct + remaining * ((stop / entry - 1) * 100)
            elif tp1 and r["low"] <= breakeven_stop:
                reason = "BE_AFTER_TP1"
                xp = realized_pct + remaining * params.be
            elif tp1 and peak_gain >= params.trail_start and giveback >= params.trail_giveback:
                reason = "TRAIL"
                xp = realized_pct + remaining * pnl
            elif r["high"] >= entry * (1 + params.tp2 / 100):
                reason = "TP2"
                xp = realized_pct + remaining * params.tp2
            elif (not tp1) and r["high"] >= entry * (1 + params.tp1 / 100):
                tp1 = True
                realized_pct += 0.5 * params.tp1
                remaining = 0.5
                stop = max(stop, breakeven_stop)
                continue
            elif i - entry_i >= params.time_stop_bars:
                reason = "TIME_STOP"
                xp = realized_pct + remaining * pnl
            elif r["close"] < r["ema21"]:
                reason = "EMA21_EXIT"
                xp = realized_pct + remaining * pnl

            if reason:
                trades.append({
                    "inst": inst,
                    "entry_i": entry_i,
                    "exit_i": i,
                    "entry_time": rows[entry_i].get("ts_iso"),
                    "exit_time": r.get("ts_iso"),
                    "pnl_pct": round(float(xp), 4),
                    "reason": reason,
                })
                inpos = False
    return trades


def max_drawdown_pct(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1 + ret / 100
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    return round(max_dd, 4)


def evaluate_params(enriched: Dict[str, List[dict]], watch: Sequence[str], params: ExitParams) -> dict:
    trades = simulate_trades(enriched, watch, params)
    returns = [t["pnl_pct"] for t in trades]
    n = len(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    avg = sum(returns) / n if n else 0.0
    win_rate = len(wins) / n * 100 if n else 0.0
    profit_factor = gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0)
    max_loss = min(returns) if returns else 0.0
    score = avg * min(n, 50) / 50 + math.log1p(max(profit_factor, 0)) * 0.08 - max_drawdown_pct(returns) * 0.03
    return {
        "params": asdict(params),
        "trades": n,
        "win_rate_pct": round(win_rate, 2),
        "avg_return_pct": round(avg, 4),
        "profit_factor": round(profit_factor, 4),
        "max_loss_pct": round(max_loss, 4),
        "max_drawdown_pct": max_drawdown_pct(returns),
        "score": round(score, 6),
        "reason_counts": reason_counts(trades),
        "sample_trades": trades[:5],
    }


def reason_counts(trades: Sequence[dict]) -> dict:
    counts = {}
    for trade in trades:
        counts[trade["reason"]] = counts.get(trade["reason"], 0) + 1
    return counts


def iter_param_grid(grid: dict) -> Iterable[ExitParams]:
    keys = ["sl", "tp1", "tp2", "be", "trail_start", "trail_giveback", "time_stop_bars"]
    for values in itertools.product(*(grid[k] for k in keys)):
        params = ExitParams(**dict(zip(keys, values)))
        if params.tp2 <= params.tp1:
            continue
        if params.trail_start < params.tp1:
            continue
        yield params


def rank_param_grid(enriched: Dict[str, List[dict]], watch: Sequence[str], grid: dict, min_trades: int = 20, top: int = 20) -> List[dict]:
    results = []
    for params in iter_param_grid(grid):
        row = evaluate_params(enriched, watch, params)
        if row["trades"] >= min_trades:
            results.append(row)
    results.sort(key=lambda r: (r["score"], r["profit_factor"], r["avg_return_pct"], r["trades"]), reverse=True)
    return results[:top]


def load_current_enriched_and_watch():
    import okx_micro_report_job as job

    con, data, since, max_ts = job.load_data()
    enriched, stats = job.summarize(data)
    state = job.load_state()
    watch = state.get("watchlist") or [s["inst"] for s in sorted(stats, key=lambda x: (x["top10_1h_count"], x["ret12"]), reverse=True)[:12]]
    try:
        con.close()
    except Exception:
        pass
    return enriched, watch, since, max_ts


def write_outputs(results: Sequence[dict], out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "micro_exit_optimization_top.json"
    csv_path = out_dir / "micro_exit_optimization_top.csv"
    json_path.write_text(json.dumps(list(results), ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = ["rank", "score", "trades", "win_rate_pct", "avg_return_pct", "profit_factor", "max_loss_pct", "max_drawdown_pct", "params", "reason_counts"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(results, 1):
            writer.writerow({**{k: row[k] for k in fieldnames if k not in ("rank", "params", "reason_counts")}, "rank": i, "params": json.dumps(row["params"], ensure_ascii=False), "reason_counts": json.dumps(row["reason_counts"], ensure_ascii=False)})
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize LIGHTOARTS OKX micro exit parameters")
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    enriched, watch, since, max_ts = load_current_enriched_and_watch()
    results = rank_param_grid(enriched, watch, DEFAULT_GRID, min_trades=args.min_trades, top=args.top)
    json_path, csv_path = write_outputs(results, Path(args.out_dir))
    print(f"watchlist: {', '.join(watch)}")
    print(f"results: {len(results)} | json: {json_path} | csv: {csv_path}")
    for i, row in enumerate(results[:10], 1):
        p = row["params"]
        print(
            f"#{i} score={row['score']:.4f} trades={row['trades']} win={row['win_rate_pct']}% "
            f"avg={row['avg_return_pct']}% pf={row['profit_factor']} maxLoss={row['max_loss_pct']}% dd={row['max_drawdown_pct']}% "
            f"SL={p['sl']} TP1={p['tp1']} TP2={p['tp2']} BE={p['be']} Trail={p['trail_start']}/{p['trail_giveback']} Time={p['time_stop_bars']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
