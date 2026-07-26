"""Popostock PostgreSQL-backed market history explorer."""

from __future__ import annotations

import gzip
import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "popostock" / "data" / "market_seed.json.gz"
SITE_DIR = BASE_DIR / "popostock" / "site"

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

CREATE TABLE IF NOT EXISTS popostock_fund_profiles (
    symbol TEXT PRIMARY KEY REFERENCES popostock_instruments(symbol) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    aum_twd BIGINT,
    aum_date TEXT,
    nav_date DATE,
    nav_value NUMERIC,
    manager TEXT,
    official_url TEXT,
    bootstrap_source_url TEXT,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_fund_holdings (
    fund_symbol TEXT NOT NULL REFERENCES popostock_fund_profiles(symbol) ON DELETE CASCADE,
    source_date DATE NOT NULL,
    stock_code TEXT,
    stock_name TEXT NOT NULL,
    weight NUMERIC,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_symbol, source_date, stock_name)
);

CREATE INDEX IF NOT EXISTS idx_popostock_fund_holdings_symbol_date
    ON popostock_fund_holdings (fund_symbol, source_date DESC);

CREATE TABLE IF NOT EXISTS popostock_fund_asset_classes (
    fund_symbol TEXT NOT NULL REFERENCES popostock_fund_profiles(symbol) ON DELETE CASCADE,
    source_date DATE NOT NULL,
    label TEXT NOT NULL,
    weight NUMERIC NOT NULL,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_symbol, source_date, label)
);

CREATE TABLE IF NOT EXISTS popostock_tracker_items (
    item_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES popostock_instruments(symbol) ON DELETE CASCADE,
    group_name TEXT NOT NULL,
    group_rank INTEGER NOT NULL,
    name TEXT NOT NULL,
    aum_twd BIGINT,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_popostock_tracker_items_group_rank
    ON popostock_tracker_items (group_name, group_rank);

CREATE TABLE IF NOT EXISTS popostock_tracker_holdings (
    item_id TEXT NOT NULL REFERENCES popostock_tracker_items(item_id) ON DELETE CASCADE,
    holding_index INTEGER NOT NULL,
    stock_code TEXT,
    stock_name TEXT NOT NULL,
    shares TEXT,
    weight NUMERIC,
    source_date TEXT,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (item_id, holding_index)
);

CREATE INDEX IF NOT EXISTS idx_popostock_tracker_holdings_stock
    ON popostock_tracker_holdings (stock_code, stock_name);

CREATE TABLE IF NOT EXISTS popostock_tracker_metadata (
    metadata_key TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    instrument_count INTEGER NOT NULL,
    candle_count INTEGER NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_page_views (
    view_date DATE PRIMARY KEY,
    view_count BIGINT NOT NULL DEFAULT 0 CHECK (view_count >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    return date.fromisoformat(str(value).replace("/", "-")) if value else None


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _popostock_redirect_target(query_items: list[tuple[str, str]]) -> str:
    query = urlencode(query_items)
    return f"/popostock?{query}" if query else "/popostock"


def _basic_value(item: dict[str, Any], label: str) -> str | None:
    for entry in item.get("basicInfo", []):
        if entry.get("label") == label:
            return entry.get("value")
    return None


def _nav_value(item: dict[str, Any]) -> float | None:
    value = str((item.get("performance") or {}).get("priceOrNav") or "").split(" ", 1)[0]
    try:
        return float(value)
    except ValueError:
        return None


async def import_seed(pool: asyncpg.Pool, seed: dict[str, Any]) -> bool:
    version = str(seed["version"])
    tracker_items = seed.get("trackerItems")
    tracker_references = seed.get("trackerReferences")
    if (
        not isinstance(tracker_items, list)
        or len(tracker_items) != int(seed.get("trackerItemCount", 0))
        or not tracker_items
    ):
        raise ValueError("Complete trackerItems are required before database import")
    if (
        not isinstance(tracker_references, list)
        or len(tracker_references) != int(seed.get("trackerReferenceCount", -1))
    ):
        raise ValueError("Complete trackerReferences are required before database import")
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

            for item in seed.get("fundProfiles", []):
                symbol = str(item["code"]).upper()
                performance = item.get("performance") or {}
                metadata = item.get("sourceMetadata") or {}
                await conn.execute(
                    """
                    INSERT INTO popostock_fund_profiles (
                        symbol, name, category, aum_twd, aum_date, nav_date,
                        nav_value, manager, official_url, bootstrap_source_url,
                        payload_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        aum_twd = EXCLUDED.aum_twd,
                        aum_date = EXCLUDED.aum_date,
                        nav_date = EXCLUDED.nav_date,
                        nav_value = EXCLUDED.nav_value,
                        manager = EXCLUDED.manager,
                        official_url = EXCLUDED.official_url,
                        bootstrap_source_url = EXCLUDED.bootstrap_source_url,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = NOW()
                    """,
                    symbol,
                    item["name"],
                    item.get("category"),
                    item.get("aumTwd"),
                    item.get("aumDate"),
                    _as_date(performance.get("date")),
                    _nav_value(item),
                    _basic_value(item, "基金經理人"),
                    metadata.get("officialUrl"),
                    metadata.get("bootstrapSourceUrl"),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                )

                await conn.execute(
                    "DELETE FROM popostock_fund_holdings WHERE fund_symbol = $1",
                    symbol,
                )
                holding_rows = [
                    (
                        symbol,
                        _as_date(holding.get("sourceDate")),
                        holding.get("stockCode"),
                        holding["stockName"],
                        holding.get("weight"),
                        holding.get("sourceTitle"),
                    )
                    for holding in item.get("holdings", [])
                    if holding.get("sourceDate")
                ]
                if holding_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_fund_holdings (
                            fund_symbol, source_date, stock_code, stock_name,
                            weight, source_title
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        holding_rows,
                    )

                await conn.execute(
                    "DELETE FROM popostock_fund_asset_classes WHERE fund_symbol = $1",
                    symbol,
                )
                asset_rows = [
                    (
                        symbol,
                        _as_date(asset.get("sourceDate")),
                        asset["label"],
                        asset["weight"],
                        asset.get("sourceTitle"),
                    )
                    for asset in item.get("assetClasses", [])
                    if asset.get("sourceDate")
                ]
                if asset_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_fund_asset_classes (
                            fund_symbol, source_date, label, weight, source_title
                        ) VALUES ($1, $2, $3, $4, $5)
                        """,
                        asset_rows,
                    )

            await conn.execute("DELETE FROM popostock_tracker_holdings")
            await conn.execute("DELETE FROM popostock_tracker_items")
            for item in seed.get("trackerItems", []):
                item_id = str(item["id"])
                symbol = str(item["code"]).upper()
                await conn.execute(
                    """
                    INSERT INTO popostock_tracker_items (
                        item_id, symbol, group_name, group_rank, name,
                        aum_twd, payload_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    item_id,
                    symbol,
                    item["group"],
                    int(item["groupRank"]),
                    item["name"],
                    item.get("aumTwd"),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                )
                holding_rows = [
                    (
                        item_id,
                        index,
                        holding.get("stockCode"),
                        holding["stockName"],
                        holding.get("shares"),
                        holding.get("weight"),
                        holding.get("sourceDate"),
                        holding.get("sourceTitle"),
                    )
                    for index, holding in enumerate(item.get("holdings", []))
                ]
                if holding_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_tracker_holdings (
                            item_id, holding_index, stock_code, stock_name,
                            shares, weight, source_date, source_title
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        holding_rows,
                    )

            await conn.execute(
                """
                INSERT INTO popostock_tracker_metadata (
                    metadata_key, payload_json
                ) VALUES ('references', $1::jsonb)
                ON CONFLICT (metadata_key) DO UPDATE SET
                    payload_json = EXCLUDED.payload_json,
                    updated_at = NOW()
                """,
                json.dumps(
                    seed.get("trackerReferences", []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

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
    async def popostock_slash(request: Request) -> RedirectResponse:
        return RedirectResponse(
            _popostock_redirect_target(list(request.query_params.multi_items())),
            status_code=308,
        )

    @app.get("/popostock", response_class=FileResponse)
    async def popostock_page() -> FileResponse:
        return FileResponse(SITE_DIR / "index.html")

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
            fund_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS profiles,
                       (SELECT COUNT(*) FROM popostock_fund_holdings) AS holdings,
                       (SELECT COUNT(*) FROM popostock_fund_asset_classes) AS asset_classes
                FROM popostock_fund_profiles
                """
            )
            tracker_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS items,
                       (SELECT COUNT(*) FROM popostock_tracker_holdings) AS holdings,
                       COUNT(*) FILTER (WHERE group_name = 'funds') AS funds,
                       COUNT(*) FILTER (WHERE group_name = 'activeEtfs') AS active_etfs,
                       COUNT(*) FILTER (WHERE group_name = 'passiveEtfs') AS passive_etfs
                FROM popostock_tracker_items
                """
            )
        return JSONResponse(
            {
                "instruments": row["instruments"],
                "candles": row["candles"],
                "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
                "fundProfiles": fund_row["profiles"],
                "fundHoldings": fund_row["holdings"],
                "fundAssetClasses": fund_row["asset_classes"],
                "trackerItems": tracker_row["items"],
                "trackerHoldings": tracker_row["holdings"],
                "trackerGroups": {
                    "funds": tracker_row["funds"],
                    "activeEtfs": tracker_row["active_etfs"],
                    "passiveEtfs": tracker_row["passive_etfs"],
                },
            }
        )

    @app.post("/popostock/api/page-view", status_code=204)
    async def record_popostock_page_view(request: Request) -> Response:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO popostock_page_views (view_date, view_count)
                VALUES ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei')::date, 1)
                ON CONFLICT (view_date) DO UPDATE SET
                    view_count = popostock_page_views.view_count + 1,
                    updated_at = NOW()
                """
            )
        return Response(status_code=204)

    @app.get("/popostock/api/page-views/summary")
    async def popostock_page_view_summary(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(view_count), 0) AS total,
                       COALESCE(SUM(view_count) FILTER (
                           WHERE view_date =
                               (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei')::date
                       ), 0) AS today,
                       MIN(view_date) AS first_date,
                       MAX(view_date) AS latest_date
                FROM popostock_page_views
                """
            )
        return JSONResponse(
            {
                "total": int(row["total"] or 0),
                "today": int(row["today"] or 0),
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

    @app.get("/popostock/api/funds")
    async def popostock_funds(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload_json
                FROM popostock_fund_profiles
                ORDER BY aum_twd DESC NULLS LAST, symbol
                """
            )
        return JSONResponse(
            [
                json.loads(row["payload_json"])
                if isinstance(row["payload_json"], str)
                else row["payload_json"]
                for row in rows
            ]
        )

    @app.get("/popostock/api/tracker")
    async def popostock_tracker(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload_json
                FROM popostock_tracker_items
                ORDER BY CASE group_name
                    WHEN 'funds' THEN 1
                    WHEN 'activeEtfs' THEN 2
                    WHEN 'passiveEtfs' THEN 3
                    ELSE 4
                END, group_rank, item_id
                """
            )
            references = await conn.fetchval(
                """
                SELECT payload_json
                FROM popostock_tracker_metadata
                WHERE metadata_key = 'references'
                """
            )
            version = await conn.fetchval(
                """
                SELECT version
                FROM popostock_sync_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )

        def json_value(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value

        return JSONResponse(
            {
                "version": version,
                "items": [json_value(row["payload_json"]) for row in rows],
                "references": json_value(references) if references is not None else [],
            }
        )

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

    app.mount(
        "/popostock",
        StaticFiles(directory=SITE_DIR, html=True),
        name="popostock-static",
    )
