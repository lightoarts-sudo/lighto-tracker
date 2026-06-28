#!/usr/bin/env python3
"""Collect OKX SPOT USDT volume Top10 5m candles into a dedicated SQLite.

Workflow:
- Fetch OKX SPOT USDT tickers and rank by quote_vol_24h.
- Persist top10_volume run metadata into top10_volume_runs.
- Persist current top10 ranking into top10_volume_rankings.
- Upsert 5m candles into dedicated candles_5m for top10 universe.
- Optional active-session tracking is intentionally omitted here so this
  feed stays simple and decoupled from the 1h-gainer training logic.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DB_PATH = Path("data/okx_top10_volume_5m_tracking.sqlite")
TZ = timezone(timedelta(hours=8))
OKX_BASE = "https://www.okx.com"
USER_AGENT = "LIGHTOARTS-top10-volume-collector/1.0"
VOLUME_TIERS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "RE-USDT",
    "HYPE-USDT",
    "OKB-USDT",
    "DOGE-USDT",
    "XRP-USDT",
    "TRX-USDT",
    "IP-USDT",
]
TOP_N_VOLUME = 10
FETCH_LIMIT = 100

# Exclude majors/stable/quotable-not-trading units from volume ranking
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
        CREATE INDEX IF NOT EXISTS idx_vol10_candles_inst_ts ON candles_5m(inst_id, ts_ms);

        CREATE TABLE IF NOT EXISTS top10_volume_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            universe_count INTEGER NOT NULL,
            ranked_count INTEGER NOT NULL,
            top10_count INTEGER NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS top10_volume_rankings (
            run_id INTEGER NOT NULL,
            rank_volume INTEGER NOT NULL,
            inst_id TEXT NOT NULL,
            base_ccy TEXT NOT NULL,
            last REAL NOT NULL,
            quote_vol_24h REAL NOT NULL,
            first_ts_ms INTEGER,
            last_ts_ms INTEGER,
            candle_count INTEGER NOT NULL,
            PRIMARY KEY(run_id, inst_id)
        );
        CREATE INDEX IF NOT EXISTS idx_top10_volume_rank_inst ON top10_volume_rankings(inst_id, run_id);
        """
    )
    con.commit()


def fetch_universe() -> list[dict]:
    tickers = okx_get("/api/v5/market/tickers", {"instType": "SPOT"}).get("data", [])
    rows: list[dict] = []
    for ticker in tickers:
        inst_id = ticker.get("instId", "")
        if not inst_id.endswith("-USDT"):
            continue
        base = inst_id.split("-")[0]
        try:
            quote_vol = float(ticker.get("volCcy24h") or 0)
            last = float(ticker.get("last") or 0)
        except (TypeError, ValueError):
            continue
        if quote_vol <= 0 or last <= 0:
            continue
        rows.append(
            {
                "inst_id": inst_id,
                "base_ccy": base,
                "quote_vol_24h": quote_vol,
                "ticker_last": last,
            }
        )
    rows.sort(key=lambda r: r["quote_vol_24h"], reverse=True)
    return rows


def parse_candles(raw: list) -> list[dict]:
    rows: list[dict] = []
    for c in raw:
        try:
            ts_ms = int(c[0])
            vol = float(c[5])
            vol_ccy = float(c[6] or 0)
        except (IndexError, TypeError, ValueError):
            continue
        if vol <= 0 and vol_ccy <= 0:
            continue
        try:
            rows.append(
                {
                    "ts_ms": ts_ms,
                    "ts_iso": iso_from_ms_taipei(ts_ms),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "vol": vol,
                    "vol_ccy": vol_ccy,
                }
            )
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def fetch_5m(inst_id: str, limit: int = FETCH_LIMIT) -> list[dict]:
    raw = okx_get("/api/v5/market/candles", {"instId": inst_id, "bar": "5m", "limit": str(limit)}).get("data", [])
    return parse_candles(raw)


def upsert_candles(con: sqlite3.Connection, inst_id: str, candles: list[dict], captured_at: str) -> None:
    con.executemany(
        """
        INSERT OR IGNORE INTO candles_5m(inst_id,ts_ms,ts_iso,open,high,low,close,vol,vol_ccy,captured_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
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


def collect_once(db_path: Path, sleep_s: float = 0.05, top_n: int = TOP_N_VOLUME) -> dict:
    captured_at = now_taipei().isoformat(timespec="seconds")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    init_db(con)

    universe = fetch_universe()
    ranked: list[dict] = []
    errors: list[str] = []

    for item in universe:
        inst_id = item["inst_id"]
        if inst_id not in VOLUME_TIERS:
            continue
        try:
            candles = fetch_5m(inst_id)
            if not candles:
                continue
            upsert_candles(con, inst_id, candles, captured_at)
            ranked.append(
                {
                    **item,
                    "last_ts_ms": candles[-1]["ts_ms"],
                    "candle_count": len(candles),
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst_id}: {exc}")
        time.sleep(sleep_s)

    ranked.sort(key=lambda r: r["quote_vol_24h"], reverse=True)
    topn = ranked[:top_n]

    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO top10_volume_runs(captured_at,universe_count,ranked_count,top10_count,notes)
        VALUES(?,?,?,?,?)
        """,
        (
            captured_at,
            len(universe),
            len(ranked),
            len(topn),
            "; ".join(errors[:5]) if errors else "",
        ),
    )
    run_id = cur.lastrowid
    cur.executemany(
        """
        INSERT INTO top10_volume_rankings(
            run_id,rank_volume,inst_id,base_ccy,last,quote_vol_24h,first_ts_ms,last_ts_ms,candle_count
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id,
                i + 1,
                r["inst_id"],
                r["base_ccy"],
                r["ticker_last"],
                r["quote_vol_24h"],
                None,
                r["last_ts_ms"],
                r["candle_count"],
            )
            for i, r in enumerate(topn)
        ],
    )
    con.commit()
    con.close()

    return {
        "captured_at": captured_at,
        "db": str(db_path),
        "universe_count": len(universe),
        "ranked_count": len(ranked),
        "top10_count": len(topn),
        "top10": [
            {
                "rank": i + 1,
                "inst_id": r["inst_id"],
                "quote_vol_24h": round(r["quote_vol_24h"], 2),
                "candle_count": r["candle_count"],
            }
            for i, r in enumerate(topn)
        ],
        "errors": errors[:10],
    }


def main() -> int:
    report = collect_once(DB_PATH)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
