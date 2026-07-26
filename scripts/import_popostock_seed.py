#!/usr/bin/env python3
"""Import the bundled Popostock seed into DATABASE_URL."""

from __future__ import annotations

import asyncio
import os

import asyncpg

import popostock


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if not database_url.startswith("postgresql://"):
        raise SystemExit("DATABASE_URL must be a PostgreSQL connection string")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            await conn.execute(popostock.SCHEMA_SQL)
        seed = popostock._read_seed()
        if not seed:
            raise SystemExit(f"Seed not found: {popostock.SEED_PATH}")
        imported = await popostock.import_seed(pool, seed)
        async with pool.acquire() as conn:
            stats = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT instrument_id) AS instruments,
                       COUNT(*) AS candles,
                       MIN(trade_date) AS first_date,
                       MAX(trade_date) AS latest_date
                FROM popostock_candles
                """
            )
            tracker = await conn.fetchrow(
                """
                SELECT COUNT(*) AS items,
                       (SELECT COUNT(*) FROM popostock_tracker_holdings) AS holdings
                FROM popostock_tracker_items
                """
            )
        print(
            f"imported={imported} version={seed['version']} "
            f"instruments={stats['instruments']} candles={stats['candles']} "
            f"range={stats['first_date']}..{stats['latest_date']} "
            f"tracker_items={tracker['items']} "
            f"tracker_holdings={tracker['holdings']}"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
