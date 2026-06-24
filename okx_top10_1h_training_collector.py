#!/usr/bin/env python3
"""Collect OKX small-cap 1H gainers' 5m candles into local SQLite.

Workflow:
- Fetch OKX SPOT USDT tickers and exclude majors/stables.
- Compute point-in-time 1H return from recent 5m candles.
- Track a research universe of current 1H return TopN (default Top20).
- Mark Top5 entries with signal flags, but keep collecting Top20 research sessions.
- Keep sessions alive after they leave Top5 while 1H change is still positive.
- Before closing failed sessions, persist the final candle that triggered the exit.
- For change_below_zero exits, keep post-exit candles for a short horizon so exit quality can be studied.
- Store 5m candles for active sessions in training-specific tables and also
  upsert them into the shared candles_5m table for reuse by existing research scripts.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DB_PATH = Path("data/okx_micro_5m_tracking.sqlite")
TZ = timezone(timedelta(hours=8))
OKX_BASE = "https://www.okx.com"
USER_AGENT = "LIGHTOARTS-top10-training-collector/1.0"

EXCLUDE = set(
    "BTC ETH SOL BNB XRP ADA DOGE TRX TON AVAX LINK DOT MATIC POL LTC BCH ETC FIL ATOM NEAR APT SUI OP ARB WLD UNI PEPE SHIB LDO ICP HBAR XLM HYPE ONDO".split()
)
STABLE_OR_FIAT = set("USDC USDG USD1 RLUSD DAI TUSD USDP EURT BRZ TRYB XAUT FDUSD PYUSD USDE".split())


def now_taipei() -> datetime:
    return datetime.now(TZ)


def iso_from_ms_taipei(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, TZ).isoformat(timespec="minutes")


def okx_get(path: str, params: dict | None = None) -> dict:
    url = OKX_BASE + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def init_db(con: sqlite3.Connection) -> None:
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
        CREATE INDEX IF NOT EXISTS idx_candles_inst_ts ON candles_5m(inst_id, ts_ms);

        CREATE TABLE IF NOT EXISTS top10_1h_training_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            universe_count INTEGER NOT NULL,
            ranked_count INTEGER NOT NULL,
            top10_count INTEGER NOT NULL,
            topn_count INTEGER NOT NULL DEFAULT 10,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS top10_1h_training_rankings (
            run_id INTEGER NOT NULL,
            rank_1h INTEGER NOT NULL,
            inst_id TEXT NOT NULL,
            base_ccy TEXT NOT NULL,
            last REAL NOT NULL,
            change_1h_pct REAL NOT NULL,
            quote_vol_24h REAL NOT NULL,
            first_ts_ms INTEGER,
            last_ts_ms INTEGER,
            candle_count INTEGER NOT NULL,
            PRIMARY KEY(run_id, inst_id)
        );
        CREATE INDEX IF NOT EXISTS idx_top10_1h_rank_inst ON top10_1h_training_rankings(inst_id, run_id);

        CREATE TABLE IF NOT EXISTS top10_1h_training_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inst_id TEXT NOT NULL,
            base_ccy TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            entered_ts_ms INTEGER NOT NULL,
            entry_rank_1h INTEGER NOT NULL,
            entry_change_1h_pct REAL NOT NULL,
            entry_price REAL NOT NULL,
            entry_signal_rank INTEGER,
            entry_is_signal_top5 INTEGER NOT NULL DEFAULT 0,
            exited_at TEXT,
            exited_ts_ms INTEGER,
            exit_reason TEXT,
            post_exit_bars_remaining INTEGER NOT NULL DEFAULT 0,
            last_seen_at TEXT NOT NULL,
            last_rank_1h INTEGER NOT NULL,
            last_change_1h_pct REAL NOT NULL,
            last_price REAL NOT NULL,
            max_change_1h_pct REAL NOT NULL,
            min_rank_1h INTEGER NOT NULL,
            candle_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_top10_1h_sessions_active ON top10_1h_training_sessions(is_active, inst_id);
        CREATE INDEX IF NOT EXISTS idx_top10_1h_sessions_inst ON top10_1h_training_sessions(inst_id, entered_ts_ms);

        CREATE TABLE IF NOT EXISTS top10_1h_training_candles (
            session_id INTEGER NOT NULL,
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
            rank_1h INTEGER,
            change_1h_pct REAL,
            PRIMARY KEY(session_id, ts_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_top10_1h_candles_inst_ts ON top10_1h_training_candles(inst_id, ts_ms);

        CREATE VIEW IF NOT EXISTS top10_1h_training_dataset AS
        SELECT
            c.session_id,
            c.inst_id,
            s.base_ccy,
            s.entered_at,
            s.exited_at,
            s.is_active,
            ROW_NUMBER() OVER (PARTITION BY c.session_id ORDER BY c.ts_ms) - 1 AS bar_index_from_entry,
            c.ts_ms,
            c.ts_iso,
            c.open,
            c.high,
            c.low,
            c.close,
            c.vol,
            c.vol_ccy,
            c.rank_1h,
            c.change_1h_pct,
            s.entry_rank_1h,
            s.entry_change_1h_pct,
            s.entry_price,
            ((c.close / s.entry_price) - 1.0) * 100.0 AS return_from_entry_pct,
            s.last_rank_1h,
            s.last_change_1h_pct,
            s.max_change_1h_pct,
            s.min_rank_1h
        FROM top10_1h_training_candles c
        JOIN top10_1h_training_sessions s ON s.id = c.session_id;
    """
    )
    # Migrate: add columns if missing
    migrations = [
        "ALTER TABLE top10_1h_training_runs ADD COLUMN topn_count INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE top10_1h_training_sessions ADD COLUMN entry_signal_rank INTEGER",
        "ALTER TABLE top10_1h_training_sessions ADD COLUMN entry_is_signal_top5 INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE top10_1h_training_sessions ADD COLUMN post_exit_bars_remaining INTEGER NOT NULL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            con.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    con.commit()


def fetch_universe(max_universe: int) -> list[dict]:
    tickers = okx_get("/api/v5/market/tickers", {"instType": "SPOT"}).get("data", [])
    rows = []
    for ticker in tickers:
        inst_id = ticker.get("instId", "")
        if not inst_id.endswith("-USDT"):
            continue
        base = inst_id.split("-")[0]
        if base in EXCLUDE or base in STABLE_OR_FIAT:
            continue
        try:
            quote_vol = float(ticker.get("volCcy24h") or 0)
            last = float(ticker.get("last") or 0)
        except (TypeError, ValueError):
            continue
        if quote_vol <= 0 or last <= 0:
            continue
        rows.append({"inst_id": inst_id, "base_ccy": base, "quote_vol_24h": quote_vol, "ticker_last": last})
    rows.sort(key=lambda r: r["quote_vol_24h"], reverse=True)
    return rows[:max_universe]


def parse_candles(raw: list) -> list[dict]:
    rows = []
    for c in raw:
        try:
            ts_ms = int(c[0])
            rows.append(
                {
                    "ts_ms": ts_ms,
                    "ts_iso": iso_from_ms_taipei(ts_ms),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "vol": float(c[5]),
                    "vol_ccy": float(c[6] or 0),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def fetch_5m(inst_id: str, limit: int = 20) -> list[dict]:
    raw = okx_get("/api/v5/market/candles", {"instId": inst_id, "bar": "5m", "limit": str(limit)}).get("data", [])
    return parse_candles(raw)


def one_hour_change(rows: list[dict]) -> tuple[float, dict, dict] | None:
    if len(rows) < 13:
        return None
    latest = rows[-1]
    base = rows[-13]
    if base["close"] <= 0:
        return None
    return (latest["close"] / base["close"] - 1.0) * 100.0, base, latest


def upsert_candles(con: sqlite3.Connection, inst_id: str, candles: list[dict], captured_at: str) -> None:
    con.executemany(
        """INSERT OR IGNORE INTO candles_5m(inst_id,ts_ms,ts_iso,open,high,low,close,vol,vol_ccy,captured_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                inst_id,
                c["ts_ms"],
                c["ts_iso"],
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                c["vol"],
                c["vol_ccy"],
                captured_at,
            )
            for c in candles
        ],
    )


def active_sessions(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM top10_1h_training_sessions WHERE is_active=1").fetchall()
    return {row["inst_id"]: row for row in rows}


def insert_session_candles(
    con: sqlite3.Connection,
    session_id: int,
    inst_id: str,
    candles: list[dict],
    captured_at: str,
    rank_1h: int | None,
    change_1h_pct: float | None,
    start_ts_ms: int,
) -> int:
    wanted = [c for c in candles if c["ts_ms"] >= start_ts_ms]
    before = con.total_changes
    con.executemany(
        """INSERT INTO top10_1h_training_candles(
               session_id,inst_id,ts_ms,ts_iso,open,high,low,close,vol,vol_ccy,captured_at,rank_1h,change_1h_pct
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(session_id, ts_ms) DO UPDATE SET
               open=excluded.open,
               high=excluded.high,
               low=excluded.low,
               close=excluded.close,
               vol=excluded.vol,
               vol_ccy=excluded.vol_ccy,
               captured_at=excluded.captured_at,
               rank_1h=excluded.rank_1h,
               change_1h_pct=excluded.change_1h_pct""",
        [
            (
                session_id,
                inst_id,
                c["ts_ms"],
                c["ts_iso"],
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                c["vol"],
                c["vol_ccy"],
                captured_at,
                rank_1h,
                change_1h_pct,
            )
            for c in wanted
        ],
    )
    return con.total_changes - before


def collect_once(
    db_path: Path,
    max_universe: int,
    sleep_s: float,
    max_rank: int = 20,
    entry_rank: int = 5,
    post_exit_bars: int = 12,
    dry_run: bool = False,
) -> dict:
    captured_at = now_taipei().isoformat(timespec="seconds")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    init_db(con)

    universe = fetch_universe(max_universe)
    ranked = []
    candle_cache: dict[str, list[dict]] = {}
    errors = []

    for item in universe:
        inst_id = item["inst_id"]
        try:
            candles = fetch_5m(inst_id, 20)
            candle_cache[inst_id] = candles
            if not candles:
                continue
            upsert_candles(con, inst_id, candles, captured_at)
            metric = one_hour_change(candles)
            if not metric:
                continue
            change, first, latest = metric
            ranked.append(
                {
                    **item,
                    "change_1h_pct": change,
                    "last": latest["close"],
                    "first_ts_ms": first["ts_ms"],
                    "last_ts_ms": latest["ts_ms"],
                    "candle_count": len(candles),
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep collector resilient
            errors.append(f"{inst_id}: {exc}")
        time.sleep(sleep_s)

    ranked.sort(key=lambda r: r["change_1h_pct"], reverse=True)
    topn = ranked[:max_rank]

    if dry_run:
        return {
            "captured_at": captured_at,
            "db": str(db_path),
            "universe_count": len(universe),
            "ranked_count": len(ranked),
            "topn": [{"rank": i + 1, "inst_id": r["inst_id"], "change_1h_pct": round(r["change_1h_pct"], 4)} for i, r in enumerate(topn)],
            "errors": errors[:10],
            "dry_run": True,
        }

    cur = con.cursor()
    cur.execute(
        "INSERT INTO top10_1h_training_runs(captured_at,universe_count,ranked_count,top10_count,topn_count,notes) VALUES(?,?,?,?,?,?)",
        (captured_at, len(universe), len(ranked), len(topn), len(topn), "; ".join(errors[:5]) if errors else ""),
    )
    run_id = cur.lastrowid
    cur.executemany(
        """INSERT INTO top10_1h_training_rankings(
               run_id,rank_1h,inst_id,base_ccy,last,change_1h_pct,quote_vol_24h,first_ts_ms,last_ts_ms,candle_count
           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                run_id,
                i + 1,
                r["inst_id"],
                r["base_ccy"],
                r["last"],
                r["change_1h_pct"],
                r["quote_vol_24h"],
                r["first_ts_ms"],
                r["last_ts_ms"],
                r["candle_count"],
            )
            for i, r in enumerate(topn)
        ],
    )

    active = active_sessions(con)
    opened, updated, closed, inserted_training_candles = [], [], [], 0

    universe_ids = {item["inst_id"] for item in universe}
    ranked_by_inst = {r["inst_id"]: r for r in ranked}
    updated_rank_map = {r["inst_id"]: i + 1 for i, r in enumerate(ranked)}

    # Update/close active sessions. Important: record the current/final candle before
    # setting an exit reason, otherwise the DB misses the candle that caused failure.
    for inst_id, sess in list(active.items()):
        session_id = sess["id"]
        start_ts_ms = sess["entered_ts_ms"]
        already_exiting = bool(sess["exit_reason"])
        r = ranked_by_inst.get(inst_id)
        rank = updated_rank_map.get(inst_id, 999)
        candles = candle_cache.get(inst_id)

        if r is not None:
            if candles is None:
                candles = fetch_5m(inst_id, 20)
            inserted_training_candles += insert_session_candles(
                con, session_id, inst_id, candles, captured_at, rank, r["change_1h_pct"], start_ts_ms
            )
            cur.execute(
                """UPDATE top10_1h_training_sessions
                   SET last_seen_at=?, last_rank_1h=?, last_change_1h_pct=?, last_price=?,
                       max_change_1h_pct=MAX(max_change_1h_pct, ?), min_rank_1h=MIN(min_rank_1h, ?)
                   WHERE id=?""",
                (captured_at, rank, r["change_1h_pct"], r["last"], r["change_1h_pct"], rank, session_id),
            )
            if already_exiting:
                remaining = max(0, int(sess["post_exit_bars_remaining"] or 0) - 1)
                cur.execute(
                    "UPDATE top10_1h_training_sessions SET post_exit_bars_remaining=?, is_active=? WHERE id=?",
                    (remaining, 1 if remaining > 0 else 0, session_id),
                )
                updated.append(inst_id)
                continue
            if r["change_1h_pct"] < 0:
                remaining = max(0, post_exit_bars - 1)
                cur.execute(
                    """UPDATE top10_1h_training_sessions
                       SET exited_at=?, exited_ts_ms=?, exit_reason='change_below_zero',
                           post_exit_bars_remaining=?, is_active=?
                       WHERE id=?""",
                    (captured_at, r["last_ts_ms"], remaining, 1 if remaining > 0 else 0, session_id),
                )
                closed.append(inst_id)
            else:
                updated.append(inst_id)
            continue

        # No ranked row for an active session: separate liquidity-universe exit from data gaps.
        if already_exiting:
            remaining = max(0, int(sess["post_exit_bars_remaining"] or 0) - 1)
            cur.execute(
                "UPDATE top10_1h_training_sessions SET post_exit_bars_remaining=?, is_active=? WHERE id=?",
                (remaining, 1 if remaining > 0 else 0, session_id),
            )
            continue

        if inst_id not in universe_ids:
            reason = "left_liquidity_universe_220"
        elif candles is not None and len(candles) < 13:
            reason = "insufficient_5m_candles"
        else:
            reason = "data_gap"
        remaining = max(0, post_exit_bars - 1)
        final_candles = candle_cache.get(inst_id)
        if final_candles is None:
            final_candles = fetch_5m(inst_id, 20)
        if final_candles:
            insert_session_candles(
                con,
                session_id,
                inst_id,
                final_candles,
                captured_at,
                sess["last_rank_1h"] if sess["last_rank_1h"] is not None else 999,
                sess["last_change_1h_pct"] if sess["last_change_1h_pct"] is not None else 0.0,
                sess["entered_ts_ms"],
            )
        cur.execute(
            """UPDATE top10_1h_training_sessions
               SET is_active=?, exited_at=?, exited_ts_ms=?, exit_reason=?, post_exit_bars_remaining=?
               WHERE id=? """,
            (
                1 if remaining > 0 else 0,
                captured_at,
                int(datetime.now(timezone.utc).timestamp() * 1000),
                reason,
                remaining,
                session_id,
            ),
        )
        closed.append(inst_id)

    # Open research sessions for current TopN/Top20 coins. Top5 is only a signal flag,
    # not the full data-collection universe.
    active = active_sessions(con)
    for rank, r in enumerate(topn, 1):
        inst_id = r["inst_id"]
        if inst_id in active or r["change_1h_pct"] <= 0:
            continue
        candles = candle_cache.get(inst_id) or fetch_5m(inst_id, 20)
        start_ts_ms = r["last_ts_ms"]
        entry_signal_rank = rank if rank <= entry_rank else None
        entry_is_signal_top5 = 1 if rank <= entry_rank else 0
        cur.execute(
            """INSERT INTO top10_1h_training_sessions(
                   inst_id,base_ccy,entered_at,entered_ts_ms,entry_rank_1h,entry_change_1h_pct,entry_price,
                   entry_signal_rank,entry_is_signal_top5,last_seen_at,last_rank_1h,last_change_1h_pct,last_price,
                   max_change_1h_pct,min_rank_1h,is_active
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                inst_id,
                r["base_ccy"],
                captured_at,
                start_ts_ms,
                rank,
                r["change_1h_pct"],
                r["last"],
                entry_signal_rank,
                entry_is_signal_top5,
                captured_at,
                rank,
                r["change_1h_pct"],
                r["last"],
                r["change_1h_pct"],
                rank,
            ),
        )
        session_id = cur.lastrowid
        opened.append(inst_id)
        inserted_training_candles += insert_session_candles(
            con, session_id, inst_id, candles, captured_at, rank, r["change_1h_pct"], start_ts_ms
        )

    cur.execute(
        """UPDATE top10_1h_training_sessions
           SET candle_count=(SELECT COUNT(*) FROM top10_1h_training_candles c WHERE c.session_id=top10_1h_training_sessions.id)
           WHERE id IN (SELECT DISTINCT session_id FROM top10_1h_training_candles)"""
    )
    con.commit()

    active_after = con.execute("SELECT COUNT(*) FROM top10_1h_training_sessions WHERE is_active=1").fetchone()[0]
    sessions_total = con.execute("SELECT COUNT(*) FROM top10_1h_training_sessions").fetchone()[0]
    training_candles_total = con.execute("SELECT COUNT(*) FROM top10_1h_training_candles").fetchone()[0]
    return {
        "captured_at": captured_at,
        "db": str(db_path),
        "run_id": run_id,
        "universe_count": len(universe),
        "ranked_count": len(ranked),
        "topn": [{"rank": i + 1, "inst_id": r["inst_id"], "change_1h_pct": round(r["change_1h_pct"], 4)} for i, r in enumerate(topn)],
        "opened": opened,
        "updated": updated,
        "closed": closed,
        "active_sessions": active_after,
        "sessions_total": sessions_total,
        "inserted_training_candles": inserted_training_candles,
        "training_candles_total": training_candles_total,
        "errors": errors[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--max-universe", type=int, default=int(os.environ.get("OKX_TOP10_MAX_UNIVERSE", "220")))
    parser.add_argument("--max-rank", type=int, default=int(os.environ.get("OKX_TOP10_MAX_RANK", "20")))
    parser.add_argument("--entry-rank", type=int, default=int(os.environ.get("OKX_TOP10_ENTRY_RANK", "5")))
    parser.add_argument("--post-exit-bars", type=int, default=int(os.environ.get("OKX_TOP10_POST_EXIT_BARS", "12")))
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("OKX_TOP10_API_SLEEP", "0.055")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = collect_once(
        Path(args.db),
        args.max_universe,
        args.sleep,
        max_rank=args.max_rank,
        entry_rank=args.entry_rank,
        post_exit_bars=args.post_exit_bars,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
