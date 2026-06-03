#!/usr/bin/env python3
"""Backtest implemented micro strategies on point-in-time 1H Top10 data.

This replays `top10_1h_training_rankings` chronologically. At each collector run,
only current 1H Top10 instruments are eligible for new entries; existing open
positions are carried forward and checked against the latest available 5m candle.

Outputs JSON + CSV summaries suitable for choosing Render paper/shadow active
strategies.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import sys
import types

# The pure strategy helpers live in crypto_bot.py, whose top-level imports include
# asyncpg for the Render app. On this Windows Hermes venv asyncpg can fail to import;
# it is irrelevant for local pure-function backtests, so stub it before import.
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.SimpleNamespace(create_pool=None)
if "fastapi" not in sys.modules:
    class _DummyFastAPI:
        def __init__(self, *args, **kwargs):
            pass
        def get(self, *args, **kwargs):
            return lambda fn: fn
        def post(self, *args, **kwargs):
            return lambda fn: fn
        def on_event(self, *args, **kwargs):
            return lambda fn: fn
    def _Query(default=None, *args, **kwargs):
        return default
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_DummyFastAPI, Query=_Query)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(HTMLResponse=str, JSONResponse=dict)

import crypto_bot as cb

ROUND_TRIP_COST_PCT = 0.16
DEFAULT_STRATEGIES = [
    "strategy1",
    "strategy2",
    "strategy2.1_surge_momentum",
    "strategy4_breakout_confirmation",
    "strategy4.1_breakout_confirmation",
    "strategy9_ema9_bounce_low_heat",
    "s18_top2h_retest_runner",
    "strategy20_6h12h_cool_vwap_reclaim",
    "strategy21_multi_tf_intersection_ema9_bounce",
    "strategy22_2h_strength_breakout_retest",
    "strategy23_top1h_clean_early_breakout",
    "strategy24_top1h_delay_rank5_chg1_5",
]
RENDER_ELIGIBLE = [s for s in DEFAULT_STRATEGIES if s != "strategy1"]


@dataclass
class SimPosition:
    inst_id: str
    entry_price: float
    entry_time: int
    qty: float = 1.0
    remaining: float = 1.0
    realized_return_pct: float = 0.0
    state: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, db_path: str, strategies: List[str], min_trades: int):
        self.db_path = db_path
        self.strategies = strategies
        self.min_trades = min_trades
        self.con = sqlite3.connect(db_path)
        self.con.row_factory = sqlite3.Row
        self.positions: Dict[str, Dict[str, SimPosition]] = {s: {} for s in strategies}
        self.trades: Dict[str, List[dict]] = {s: [] for s in strategies}
        self.entry_signals: Dict[str, int] = {s: 0 for s in strategies}
        self.skipped_no_candles = 0

    def db_stats(self) -> dict:
        stats = {}
        for name, sql in {
            "runs": "select count(*) from top10_1h_training_runs",
            "rankings": "select count(*) from top10_1h_training_rankings",
            "sessions": "select count(*) from top10_1h_training_sessions",
            "closed_sessions": "select count(*) from top10_1h_training_sessions where is_active=0",
            "active_sessions": "select count(*) from top10_1h_training_sessions where is_active=1",
            "candles_5m": "select count(*) from candles_5m",
        }.items():
            stats[name] = self.con.execute(sql).fetchone()[0]
        r = self.con.execute("select min(captured_at), max(captured_at) from top10_1h_training_runs").fetchone()
        stats["first_run"], stats["last_run"] = r[0], r[1]
        r = self.con.execute("select count(distinct inst_id) from top10_1h_training_rankings").fetchone()
        stats["top10_distinct_instruments"] = r[0]
        return stats

    def iter_runs(self, limit: Optional[int] = None):
        sql = """
            select r.id as run_id, r.captured_at, k.rank_1h, k.inst_id, k.base_ccy,
                   k.last, k.change_1h_pct, k.quote_vol_24h, k.last_ts_ms
            from top10_1h_training_runs r
            join top10_1h_training_rankings k on k.run_id = r.id
            order by r.id, k.rank_1h
        """
        rows_by_run = defaultdict(list)
        for row in self.con.execute(sql):
            rows_by_run[int(row["run_id"])].append(row)
        count = 0
        for run_id in sorted(rows_by_run):
            yield run_id, rows_by_run[run_id]
            count += 1
            if limit and count >= limit:
                break

    def load_candles(self, inst_id: str, ts_ms: int, limit: int = 240) -> List[dict]:
        rows = list(self.con.execute(
            """
            select ts_ms, open, high, low, close, vol_ccy, vol
            from candles_5m
            where inst_id=? and ts_ms<=?
            order by ts_ms desc
            limit ?
            """,
            (inst_id, ts_ms, limit),
        ))
        rows.reverse()
        return [
            {
                "time": int(r["ts_ms"]),
                "closeTime": int(r["ts_ms"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["vol_ccy"] or r["vol"] or 0.0),
            }
            for r in rows
        ]

    def build_sources(self, rows: List[sqlite3.Row]) -> Tuple[dict, list, list, list, list, list]:
        sources = {}
        for r in rows:
            inst_id = r["inst_id"]
            ts_ms = int(r["last_ts_ms"] or 0)
            if ts_ms <= 0:
                continue
            candles = self.load_candles(inst_id, ts_ms)
            if len(candles) < 61:
                self.skipped_no_candles += 1
                continue
            ticker = {
                "instId": inst_id,
                "_pct24": 0.0,
                "_quoteVol": float(r["quote_vol_24h"] or 0.0),
                # No bid/ask in historical DB; signal helpers treat missing spread as OK.
                "bidPx": None,
                "askPx": None,
            }
            signal = cb.micro_trend_signal(ticker, candles)
            # Use collector's point-in-time 1H rank/change for strategy24 and reporting.
            signal["rank1h"] = int(r["rank_1h"])
            signal["collectorChange1hPct"] = float(r["change_1h_pct"] or 0.0)
            sources[inst_id] = {"signal": signal, "candles": candles, "ticker": ticker, "rank_1h": int(r["rank_1h"])}
        candidates = [dict(s["signal"]) for s in sources.values()]
        ranking1h = sorted(candidates, key=lambda row: row.get("pct1h", 0), reverse=True)
        ranking2h = sorted(candidates, key=lambda row: row.get("pct2h", 0), reverse=True)
        ranking3h = sorted(candidates, key=lambda row: row.get("pct3h", 0), reverse=True)
        ranking6h = sorted(candidates, key=lambda row: row.get("pct6h", 0), reverse=True)
        ranking12h = sorted(candidates, key=lambda row: row.get("pct12h", 0), reverse=True)
        return sources, ranking1h, ranking2h, ranking3h, ranking6h, ranking12h

    def active_inst_ids(self) -> set:
        ids = set()
        for pos_by_inst in self.positions.values():
            ids.update(pos_by_inst.keys())
        return ids

    def add_active_sources(self, sources: dict, run_ts_ms: int):
        for inst_id in self.active_inst_ids():
            if inst_id in sources:
                continue
            candles = self.load_candles(inst_id, run_ts_ms)
            if len(candles) < 61:
                continue
            ticker = {"instId": inst_id, "_pct24": 0.0, "_quoteVol": 0.0, "bidPx": None, "askPx": None}
            signal = cb.micro_trend_signal(ticker, candles)
            signal["rank1h"] = None
            signal["collectorChange1hPct"] = None
            sources[inst_id] = {"signal": signal, "candles": candles, "ticker": ticker, "rank_1h": None}

    def close_or_update(self, strategy: str, inst_id: str, signal: dict, price: float, should_exit: Callable[[dict, dict, float], bool]) -> bool:
        pos = self.positions[strategy].get(inst_id)
        if not pos:
            return False
        cb.update_micro_position_state(pos.state, price, signal)
        if not should_exit(signal, pos.state, price):
            return False
        exit_price = float(signal.get("exitPrice") or price)
        fraction = float(signal.get("exitFraction") or 1.0)
        fraction = max(0.0, min(fraction, pos.remaining))
        ret = ((exit_price / pos.entry_price) - 1.0) * 100.0 if pos.entry_price else 0.0
        pos.realized_return_pct += ret * fraction
        pos.remaining -= fraction
        if pos.remaining <= 1e-9 or fraction >= 1.0:
            gross = pos.realized_return_pct
            net = gross - ROUND_TRIP_COST_PCT
            self.trades[strategy].append({
                "strategy": strategy,
                "inst_id": inst_id,
                "entry_time": pos.entry_time,
                "exit_time": signal.get("time"),
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "gross_return_pct": gross,
                "net_return_pct": net,
                "exit_reason": signal.get("exitReason", "exit"),
            })
            del self.positions[strategy][inst_id]
        return True

    def enter(self, strategy: str, inst_id: str, price: float, signal: dict):
        if inst_id in self.positions[strategy]:
            return
        state = cb.new_micro_state()
        state.update({
            "assetQty": 1.0,
            "avgEntry": price,
            "margin": 1.0,
            "notional": price,
            "peakPrice": price,
            "entryTime": signal.get("time", 0),
            "trades": 1,
        })
        self.positions[strategy][inst_id] = SimPosition(inst_id=inst_id, entry_price=price, entry_time=signal.get("time", 0), state=state)
        self.entry_signals[strategy] += 1

    def signal_for(self, strategy: str, source: dict, rank_1h: Optional[int]) -> dict:
        inst_id = source["ticker"]["instId"]
        ticker = {"instId": inst_id, "_pct24": source["signal"].get("pct24", 0), "_quoteVol": source["signal"].get("quoteVolume24h", 0), "bidPx": None, "askPx": None}
        candles = source["candles"]
        if strategy == "strategy1":
            return dict(source["signal"])
        if strategy == "strategy2":
            sig = dict(source["signal"])
            sig["buy"] = cb.micro_strategy2_should_enter(sig)
            if sig["buy"]:
                sig["reason"] = "strategy2_surge_momentum"
            return sig
        if strategy == "strategy2.1_surge_momentum":
            return cb.micro_strategy21_surge_signal(dict(source["signal"]))
        if strategy == "strategy4_breakout_confirmation":
            return cb.micro_strategy4_signal(ticker, candles)
        if strategy == "strategy4.1_breakout_confirmation":
            return cb.micro_strategy41_signal(ticker, candles)
        if strategy == "strategy9_ema9_bounce_low_heat":
            return cb.micro_strategy9_signal(ticker, candles)
        if strategy == "s18_top2h_retest_runner":
            return cb.micro_strategy18_signal(ticker, candles)
        if strategy == "strategy20_6h12h_cool_vwap_reclaim":
            return cb.micro_strategy20_signal(ticker, candles)
        if strategy == "strategy21_multi_tf_intersection_ema9_bounce":
            return cb.micro_strategy21_signal(ticker, candles)
        if strategy == "strategy22_2h_strength_breakout_retest":
            return cb.micro_strategy22_signal(ticker, candles)
        if strategy == "strategy23_top1h_clean_early_breakout":
            return cb.micro_strategy23_signal(ticker, candles)
        if strategy == "strategy24_top1h_delay_rank5_chg1_5":
            return cb.micro_strategy24_signal(ticker, candles, rank_1h=rank_1h)
        raise KeyError(strategy)

    def should_exit_fn(self, strategy: str):
        return {
            "strategy1": cb.micro_should_exit,
            "strategy2": cb.micro_strategy2_should_exit,
            "strategy2.1_surge_momentum": cb.micro_strategy21_surge_should_exit,
            "strategy4_breakout_confirmation": cb.micro_strategy4_should_exit,
            "strategy4.1_breakout_confirmation": cb.micro_strategy41_should_exit,
            "strategy9_ema9_bounce_low_heat": cb.micro_strategy9_should_exit,
            "s18_top2h_retest_runner": cb.micro_strategy18_should_exit,
            "strategy20_6h12h_cool_vwap_reclaim": cb.micro_strategy20_should_exit,
            "strategy21_multi_tf_intersection_ema9_bounce": cb.micro_strategy21_should_exit,
            "strategy22_2h_strength_breakout_retest": cb.micro_strategy22_should_exit,
            "strategy23_top1h_clean_early_breakout": cb.micro_strategy23_should_exit,
            "strategy24_top1h_delay_rank5_chg1_5": cb.micro_strategy24_should_exit,
        }[strategy]

    def step_strategy24_pending(self, inst_id: str, source: dict, signal: dict, rank_1h: Optional[int]):
        strategy = "strategy24_top1h_delay_rank5_chg1_5"
        pseudo = self.positions[strategy].get(f"PENDING::{inst_id}")
        price = source["candles"][-1]["close"]
        if pseudo:
            pending = pseudo.state.get("strategy24PendingEntry") or {}
            if signal.get("time", 0) >= pending.get("readyTime", 0) and signal.get("strategy24SessionStillTop10"):
                del self.positions[strategy][f"PENDING::{inst_id}"]
                signal["buy"] = True
                signal["reason"] = "strategy24_delay1_rank5_chg1_5_confirmed"
                self.enter(strategy, inst_id, price, signal)
            elif signal.get("time", 0) > pending.get("expiresAt", 0) or not signal.get("strategy24SessionStillTop10"):
                del self.positions[strategy][f"PENDING::{inst_id}"]
        elif signal.get("strategy24SeedOk") and rank_1h is not None:
            delay_ms = cb.CONFIG["microStrategy24DelayBars"] * cb.micro_bar_minutes() * 60 * 1000
            state = cb.new_micro_state()
            state["strategy24PendingEntry"] = {
                "time": signal["time"],
                "readyTime": signal["time"] + delay_ms,
                "expiresAt": signal["time"] + delay_ms + (cb.micro_bar_minutes() * 60 * 1000),
                "entryRank1h": rank_1h,
                "entryChange1hPct": signal.get("pct1h", 0),
                "entryPrice": price,
            }
            self.positions[strategy][f"PENDING::{inst_id}"] = SimPosition(inst_id=f"PENDING::{inst_id}", entry_price=0, entry_time=signal["time"], state=state)

    def run(self, limit_runs: Optional[int] = None) -> dict:
        run_count = 0
        for run_id, rows in self.iter_runs(limit_runs):
            run_count += 1
            sources, ranking1h, ranking2h, ranking3h, ranking6h, ranking12h = self.build_sources(rows)
            run_ts_ms = max(int(r["last_ts_ms"] or 0) for r in rows)
            self.add_active_sources(sources, run_ts_ms)

            rank_maps = {
                "strategy2": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy2TopN"]], 1)},
                "strategy2.1_surge_momentum": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy21SurgeTopN"]], 1)},
                "strategy9_ema9_bounce_low_heat": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy9TopN"]], 1)},
                "s18_top2h_retest_runner": {s["instId"]: i for i, s in enumerate(ranking2h[:cb.CONFIG["microStrategy18TopN"]], 1)},
                "strategy20_6h12h_cool_vwap_reclaim": {s["instId"]: i for i, s in enumerate(ranking12h[:cb.CONFIG["microStrategy20TopN"]], 1)},
                "strategy21_multi_tf_intersection_ema9_bounce": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy21TopN"]], 1)},
                "strategy22_2h_strength_breakout_retest": {s["instId"]: i for i, s in enumerate(ranking2h[:cb.CONFIG["microStrategy22TopN"]], 1)},
                "strategy23_top1h_clean_early_breakout": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy23TopN"]], 1)},
                "strategy24_top1h_delay_rank5_chg1_5": {s["instId"]: i for i, s in enumerate(ranking1h[:cb.CONFIG["microStrategy24SessionTopN"]], 1)},
            }

            for strategy in self.strategies:
                if strategy == "strategy24_top1h_delay_rank5_chg1_5":
                    # Evaluate active positions first, then pending/new seeds over current Top10/rank scope.
                    pass
                allowed = set(sources.keys())
                if strategy in rank_maps:
                    allowed = set(rank_maps[strategy]) | set(self.positions[strategy])
                    allowed = {i for i in allowed if not i.startswith("PENDING::")}
                for inst_id in list(allowed):
                    source = sources.get(inst_id)
                    if not source:
                        continue
                    rank_1h = rank_maps.get(strategy, {}).get(inst_id) if strategy in rank_maps else source.get("rank_1h")
                    signal = self.signal_for(strategy, source, rank_1h)
                    price = source["candles"][-1]["close"]
                    if inst_id in self.positions[strategy]:
                        self.close_or_update(strategy, inst_id, signal, price, self.should_exit_fn(strategy))
                    elif strategy == "strategy1":
                        # Legacy strategy1 has a pending confirmation stage.
                        # For compact Top10 replay, count only confirmed immediate buy signals.
                        if signal.get("buy"):
                            self.enter(strategy, inst_id, price, signal)
                    elif strategy == "strategy24_top1h_delay_rank5_chg1_5":
                        self.step_strategy24_pending(inst_id, source, signal, rank_1h)
                    elif signal.get("buy"):
                        self.enter(strategy, inst_id, price, signal)

        summaries = [self.summarize_strategy(s) for s in self.strategies]
        summaries.sort(key=lambda r: (r["eligible_win_rate_gt_40"], r["closed_trades"], r["net_avg_return"], r["win_rate"]), reverse=True)
        return {
            "db_stats": self.db_stats(),
            "runs_replayed": run_count,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "min_trades": self.min_trades,
            "strategies_tested": self.strategies,
            "render_eligible_strategies": RENDER_ELIGIBLE,
            "summaries": summaries,
            "selected_for_render": [r["strategy"] for r in summaries if r["strategy"] in RENDER_ELIGIBLE and r["eligible_win_rate_gt_40"]],
            "skipped_no_candles": self.skipped_no_candles,
        }

    def summarize_strategy(self, strategy: str) -> dict:
        trades = self.trades[strategy]
        net = [t["net_return_pct"] for t in trades]
        gross = [t["gross_return_pct"] for t in trades]
        wins = [r for r in net if r > 0]
        losses = [r for r in net if r <= 0]
        gp = sum(wins)
        gl = -sum(losses)
        return {
            "strategy": strategy,
            "entry_signals": self.entry_signals[strategy],
            "closed_trades": len(trades),
            "open_positions": len([k for k in self.positions[strategy] if not k.startswith("PENDING::")]),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
            "avg_return": (sum(gross) / len(gross)) if gross else 0.0,
            "median_return": median(gross) if gross else 0.0,
            "net_avg_return": (sum(net) / len(net)) if net else 0.0,
            "profit_factor": (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0),
            "max_loss": min(net) if net else 0.0,
            "exit_reason_counts": dict(Counter(t["exit_reason"] for t in trades)),
            "eligible_win_rate_gt_40": len(trades) >= self.min_trades and ((len(wins) / len(trades) * 100.0) if trades else 0.0) > 40.0,
        }


def write_csv(path: str, summaries: List[dict]):
    fields = ["strategy", "entry_signals", "closed_trades", "open_positions", "wins", "losses", "win_rate", "avg_return", "median_return", "net_avg_return", "profit_factor", "max_loss", "eligible_win_rate_gt_40", "exit_reason_counts"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in summaries:
            row = dict(r)
            row["exit_reason_counts"] = json.dumps(row["exit_reason_counts"], ensure_ascii=False, sort_keys=True)
            for key in ["win_rate", "avg_return", "median_return", "net_avg_return", "profit_factor", "max_loss"]:
                row[key] = f"{float(row[key]):.6f}"
            w.writerow({k: row.get(k) for k in fields})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/okx_micro_5m_tracking.sqlite")
    ap.add_argument("--json-out", default="data/top10_1h_all_strategy_backtest_latest.json")
    ap.add_argument("--csv-out", default="data/top10_1h_all_strategy_backtest_latest.csv")
    ap.add_argument("--min-trades", type=int, default=5, help="Minimum closed trades before a >40% win-rate strategy is selectable")
    ap.add_argument("--limit-runs", type=int, default=None)
    args = ap.parse_args()
    bt = Backtester(args.db, DEFAULT_STRATEGIES, args.min_trades)
    out = bt.run(args.limit_runs)
    Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(args.csv_out, out["summaries"])
    compact = {
        "db_stats": out["db_stats"],
        "runs_replayed": out["runs_replayed"],
        "round_trip_cost_pct": out["round_trip_cost_pct"],
        "min_trades": out["min_trades"],
        "selected_for_render": out["selected_for_render"],
        "summaries": out["summaries"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
