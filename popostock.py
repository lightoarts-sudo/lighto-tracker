"""Popostock PostgreSQL-backed market history explorer."""

from __future__ import annotations

import gzip
import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "popostock" / "data" / "market_seed.json.gz"
PAGE_PATH = BASE_DIR / "popostock" / "index.html"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS popostock_instruments (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    source_title TEXT,
    source_url TEXT,
    source_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_candles (
    instrument_id BIGINT NOT NULL REFERENCES popostock_instruments(id) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d',
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL,
    volume BIGINT,
    turnover NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id, trade_date, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_popostock_candles_symbol_date
    ON popostock_candles (instrument_id, trade_date DESC);

CREATE TABLE IF NOT EXISTS popostock_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    instrument_count INTEGER NOT NULL,
    candle_count INTEGER NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

UPSERT_CANDLE_SQL = """
INSERT INTO popostock_candles
    (instrument_id, trade_date, timeframe, open, high, low, close, volume, turnover)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8)
ON CONFLICT (instrument_id, trade_date, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    turnover = EXCLUDED.turnover,
    updated_at = NOW()
"""


def _read_seed() -> dict[str, Any] | None:
    if not SEED_PATH.exists():
        return None
    with gzip.open(SEED_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


async def import_seed(pool: asyncpg.Pool, seed: dict[str, Any]) -> bool:
    version = str(seed["version"])
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM popostock_sync_runs WHERE version = $1", version
        )
        if exists:
            return False

        async with conn.transaction():
            for item in seed.get("instruments", []):
                instrument_id = await conn.fetchval(
                    """
                    INSERT INTO popostock_instruments
                        (symbol, name, category, source_title, source_url, source_date)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        source_title = EXCLUDED.source_title,
                        source_url = EXCLUDED.source_url,
                        source_date = EXCLUDED.source_date,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    item["symbol"],
                    item["name"],
                    item["category"],
                    item.get("sourceTitle"),
                    item.get("sourceUrl"),
                    _as_date(item.get("sourceDate")),
                )
                rows = []
                for candle in item.get("candles", []):
                    if len(candle) < 7 or candle[4] is None:
                        continue
                    rows.append(
                        (
                            instrument_id,
                            _as_date(candle[0]),
                            candle[1],
                            candle[2],
                            candle[3],
                            candle[4],
                            candle[5],
                            candle[6],
                        )
                    )
                if rows:
                    await conn.executemany(UPSERT_CANDLE_SQL, rows)

            await conn.execute(
                """
                INSERT INTO popostock_sync_runs
                    (version, instrument_count, candle_count)
                VALUES ($1, $2, $3)
                """,
                version,
                int(seed.get("instrumentCount", 0)),
                int(seed.get("candleCount", 0)),
            )
    return True


def install_popostock(app: FastAPI, database_url: str) -> None:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    @app.on_event("startup")
    async def popostock_startup() -> None:
        if not database_url.startswith("postgresql://"):
            LOGGER.warning("Popostock disabled: PostgreSQL DATABASE_URL is unavailable")
            app.state.popostock_pool = None
            return
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
        app.state.popostock_pool = pool
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        seed = _read_seed()
        if seed:
            imported = await import_seed(pool, seed)
            LOGGER.info(
                "Popostock seed %s: %s",
                seed["version"],
                "imported" if imported else "already current",
            )

    @app.on_event("shutdown")
    async def popostock_shutdown() -> None:
        pool = getattr(app.state, "popostock_pool", None)
        if pool:
            await pool.close()

    def pool_for(request: Request) -> asyncpg.Pool:
        pool = getattr(request.app.state, "popostock_pool", None)
        if not pool:
            raise HTTPException(status_code=503, detail="Popostock database unavailable")
        return pool

    @app.get("/popostock/")
    async def popostock_slash() -> RedirectResponse:
        return RedirectResponse("/popostock", status_code=308)

    @app.get("/popostock", response_class=HTMLResponse)
    async def popostock_page() -> HTMLResponse:
        return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"))

    @app.get("/popostock/api/summary")
    async def popostock_summary(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT i.id) AS instruments,
                       COUNT(c.trade_date) AS candles,
                       MIN(c.trade_date) AS first_date,
                       MAX(c.trade_date) AS latest_date
                FROM popostock_instruments i
                LEFT JOIN popostock_candles c ON c.instrument_id = i.id
                """
            )
        return JSONResponse(
            {
                "instruments": row["instruments"],
                "candles": row["candles"],
                "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
            }
        )

    @app.get("/popostock/api/instruments")
    async def popostock_instruments(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT instrument_id, trade_date, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY instrument_id ORDER BY trade_date DESC
                           ) AS rn
                    FROM popostock_candles
                    WHERE timeframe = '1d'
                ), stats AS (
                    SELECT instrument_id, COUNT(*) AS points,
                           MIN(trade_date) AS first_date, MAX(trade_date) AS latest_date
                    FROM popostock_candles
                    WHERE timeframe = '1d'
                    GROUP BY instrument_id
                )
                SELECT i.symbol, i.name, i.category, i.source_title, i.source_url,
                       i.source_date, s.points, s.first_date, s.latest_date,
                       latest.close AS latest_close, previous.close AS previous_close
                FROM popostock_instruments i
                LEFT JOIN stats s ON s.instrument_id = i.id
                LEFT JOIN ranked latest
                       ON latest.instrument_id = i.id AND latest.rn = 1
                LEFT JOIN ranked previous
                       ON previous.instrument_id = i.id AND previous.rn = 2
                ORDER BY CASE i.category
                    WHEN 'index' THEN 1 WHEN 'active_etf' THEN 2
                    WHEN 'passive_etf' THEN 3 ELSE 4 END,
                    i.symbol
                """
            )
        payload = []
        for row in rows:
            latest = _number(row["latest_close"])
            previous = _number(row["previous_close"])
            change = None
            if latest is not None and previous not in (None, 0):
                change = round((latest / previous - 1) * 100, 3)
            payload.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "category": row["category"],
                    "sourceTitle": row["source_title"],
                    "sourceUrl": row["source_url"],
                    "sourceDate": row["source_date"].isoformat() if row["source_date"] else None,
                    "points": row["points"] or 0,
                    "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                    "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
                    "latestClose": latest,
                    "changePct": change,
                }
            )
        return JSONResponse(payload)

    @app.get("/popostock/api/candles/{symbol}")
    async def popostock_candles(
        symbol: str,
        request: Request,
        limit: int = Query(12000, ge=20, le=20000),
    ) -> JSONResponse:
        pool = pool_for(request)
        symbol = symbol.upper().strip()
        if not symbol.replace("-", "").isalnum():
            raise HTTPException(status_code=400, detail="Invalid symbol")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM (
                    SELECT c.trade_date, c.open, c.high, c.low, c.close,
                           c.volume, c.turnover
                    FROM popostock_candles c
                    JOIN popostock_instruments i ON i.id = c.instrument_id
                    WHERE i.symbol = $1 AND c.timeframe = '1d'
                    ORDER BY c.trade_date DESC
                    LIMIT $2
                ) history
                ORDER BY trade_date
                """,
                symbol,
                limit,
            )
        if not rows:
            raise HTTPException(status_code=404, detail="Symbol not found")
        return JSONResponse(
            [
                {
                    "time": row["trade_date"].isoformat(),
                    "open": _number(row["open"]),
                    "high": _number(row["high"]),
                    "low": _number(row["low"]),
                    "close": _number(row["close"]),
                    "volume": _number(row["volume"]),
                    "turnover": _number(row["turnover"]),
                }
                for row in rows
            ]
        )
