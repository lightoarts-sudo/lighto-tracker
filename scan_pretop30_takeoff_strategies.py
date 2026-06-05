#!/usr/bin/env python
"""Scan pre-Top10 takeoff candidates from point-in-time OKX 1H rankings.

This is intentionally research-only: it looks at rank 11-30 coins that are
already rising but have not yet entered the 1H Top10, then measures whether
buying before Top10 entry has better expectancy than chasing Top10 membership.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

ROUND_TRIP_COST_PCT = 0.16


@dataclass(frozen=True)
class Params:
    rank_min: int
    rank_max: int
    chg_min: float
    chg_max: float
    vol_min: float
    hold_snaps: int
    stop_pct: float
    require_enter_top10: bool
    max_enter_snaps: int

    @property
    def name(self) -> str:
        req = f"enter{self.max_enter_snaps}" if self.require_enter_top10 else "pre"
        return (
            f"pretop30_{req}_r{self.rank_min}_{self.rank_max}_"
            f"chg{self.chg_min:g}_{self.chg_max:g}_vol{self.vol_min:g}_"
            f"sl{self.stop_pct:g}_h{self.hold_snaps}"
        ).replace(".", "")


def load_snapshots(con: sqlite3.Connection):
    snaps = []
    for sid, ts in con.execute("select id, captured_at from snapshots order by id"):
        ranks = {
            row["inst_id"]: dict(row)
            for row in con.execute("select * from rankings where snapshot_id=?", (sid,))
        }
        snaps.append({"id": sid, "ts": ts, "ranks": ranks})
    return snaps


def candidate_events(snaps):
    prev_top10 = set()
    in_pretop = set()
    events = []
    for idx, snap in enumerate(snaps):
        ranks = snap["ranks"]
        top10 = {inst for inst, r in ranks.items() if int(r["rank_1h"]) <= 10}
        current_pretop = {inst for inst, r in ranks.items() if 11 <= int(r["rank_1h"]) <= 30}
        for inst, r in ranks.items():
            rank = int(r["rank_1h"])
            if not 11 <= rank <= 30:
                continue
            if inst in prev_top10 or inst in in_pretop:
                continue
            events.append({
                "idx": idx,
                "ts": snap["ts"],
                "inst_id": inst,
                "rank": rank,
                "chg": float(r["change_1h_pct"] or 0),
                "vol_ratio": float(r["vol_ratio_5m"] or 0),
                "price": float(r["last"]),
            })
        prev_top10 = top10
        in_pretop = current_pretop
    return events


def simulate(snaps, event, p: Params):
    if not (p.rank_min <= event["rank"] <= p.rank_max):
        return None
    if not (p.chg_min <= event["chg"] <= p.chg_max):
        return None
    if event["vol_ratio"] < p.vol_min:
        return None
    idx = event["idx"]
    inst = event["inst_id"]
    entry = event["price"]
    if entry <= 0:
        return None

    entered_top10_at = None
    best_rank = event["rank"]
    max_chg = event["chg"]
    exit_price = entry
    exit_reason = "hold"
    stop_price = entry * (1 - p.stop_pct / 100.0)

    end = min(len(snaps) - 1, idx + p.hold_snaps)
    for j in range(idx + 1, end + 1):
        rr = snaps[j]["ranks"].get(inst)
        if not rr:
            exit_reason = "left_top30"
            break
        price = float(rr["last"])
        exit_price = price
        rank = int(rr["rank_1h"])
        best_rank = min(best_rank, rank)
        max_chg = max(max_chg, float(rr["change_1h_pct"] or 0))
        if rank <= 10 and entered_top10_at is None:
            entered_top10_at = j - idx
        # Snapshot-level stop: conservative because intrabar low is unknown here.
        if price <= stop_price:
            exit_price = price
            exit_reason = "stop_snapshot"
            break

    if p.require_enter_top10 and (entered_top10_at is None or entered_top10_at > p.max_enter_snaps):
        return None

    gross = (exit_price / entry - 1) * 100.0
    return {
        **event,
        "strategy": p.name,
        "entered_top10_at": entered_top10_at,
        "best_rank": best_rank,
        "max_chg": max_chg,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
        "net_return_pct": gross - ROUND_TRIP_COST_PCT,
    }


def summarize(p: Params, trades):
    vals = [t["net_return_pct"] for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    days = defaultdict(float)
    reasons = Counter()
    for t in trades:
        days[t["ts"][:10]] += t["net_return_pct"]
        reasons[t["exit_reason"]] += 1
    return {
        "strategy": p.name,
        "params": p.__dict__,
        "trades": len(trades),
        "win_rate": len(wins) / len(vals) * 100 if vals else 0,
        "net_avg_return": sum(vals) / len(vals) if vals else 0,
        "median_net_return": median(vals) if vals else 0,
        "profit_factor": gp / gl if gl else 999,
        "max_loss": min(vals) if vals else 0,
        "day_win_rate": sum(1 for v in days.values() if v > 0) / len(days) * 100 if days else 0,
        "worst_day": min(days.values()) if days else 0,
        "best_day": max(days.values()) if days else 0,
        "exit_reason_counts": dict(reasons),
    }


def build_grid():
    grid = []
    for rank_min, rank_max in [(11, 15), (16, 20), (21, 30), (11, 20), (11, 30)]:
        for chg_min, chg_max in [(0.3, 1), (0.5, 1), (1, 2), (0.5, 2), (2, 3), (3, 5)]:
            for vol_min in [0, 0.5, 1.0, 1.5]:
                for hold in [2, 3, 6, 9, 12]:
                    for stop in [0.8, 1.0, 1.5, 2.0]:
                        for require_enter, max_enter in [(False, 0), (True, 3), (True, 6)]:
                            grid.append(Params(rank_min, rank_max, chg_min, chg_max, vol_min, hold, stop, require_enter, max_enter))
    return grid


def scan_snapshots(snaps, min_trades=60, grid=None, db_label=None):
    """Return summaries split by implementable live filters vs oracle diagnostics.

    `oracle_summaries` are useful for measuring whether future Top10 entry would
    have confirmed the thesis, but they cannot be traded because they filter on
    information unavailable at entry time.
    """
    events = candidate_events(snaps)
    summaries = []
    for p in grid or build_grid():
        trades = [t for e in events if (t := simulate(snaps, e, p))]
        if len(trades) >= min_trades:
            summaries.append(summarize(p, trades))
    live_summaries = [s for s in summaries if not s["params"]["require_enter_top10"]]
    oracle_summaries = [s for s in summaries if s["params"]["require_enter_top10"]]
    live_summaries.sort(key=lambda s: (s["net_avg_return"], s["profit_factor"], s["trades"]), reverse=True)
    oracle_summaries.sort(key=lambda s: (s["net_avg_return"], s["profit_factor"], s["trades"]), reverse=True)
    summaries = live_summaries + oracle_summaries
    return {
        "db": db_label,
        "note": "live_summaries are implementable entry filters; oracle_summaries require future Top10 entry confirmation and are for diagnostics only, not tradable signals.",
        "snapshot_count": len(snaps),
        "first_snapshot": snaps[0]["ts"] if snaps else None,
        "last_snapshot": snaps[-1]["ts"] if snaps else None,
        "events": len(events),
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "min_trades": min_trades,
        "summaries": summaries,
        "live_summaries": live_summaries,
        "oracle_summaries": oracle_summaries,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/okx_micro_5m_tracking.sqlite")
    ap.add_argument("--json-out", default="data/pretop30_takeoff_scan_latest.json")
    ap.add_argument("--csv-out", default="data/pretop30_takeoff_scan_latest.csv")
    ap.add_argument("--min-trades", type=int, default=60)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    out = scan_snapshots(load_snapshots(con), min_trades=args.min_trades, db_label=args.db)
    Path(args.json_out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        fields = ["strategy", "trades", "win_rate", "net_avg_return", "median_net_return", "profit_factor", "max_loss", "day_win_rate", "worst_day", "best_day"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in out["summaries"]:
            w.writerow({k: s[k] for k in fields})
    print(json.dumps({**out, "summaries": out["summaries"][:20]}, indent=2))


if __name__ == "__main__":
    main()
