#!/usr/bin/env python3
"""Probe top10_1h_training_sessions schema + sample closed trades."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "okx_micro_5m_tracking.sqlite"

sqlite3.register_adapter(bool, int)
sqlite3.register_converter("BOOLEAN", lambda v: bool(int(v)))


def main() -> int:
    con = sqlite3.connect(DB)
    try:
        cur = con.cursor()
        cur.execute("pragma table_info(top10_1h_training_sessions);")
        rows = cur.fetchall()
        print("[columns]")
        for r in rows:
            print(r)

        cur.execute(
            """
            select
              id,
              inst_id,
              entered_at,
              exited_at,
              exit_reason,
              entry_price,
              last_price,
              entry_change_1h_pct,
              last_change_1h_pct
            from top10_1h_training_sessions
            where exited_at is not null
            order by id desc
            limit 10
            """
        )
        rows = cur.fetchall()
        print("[sample closed rows]")
        for r in rows:
            print(r)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
