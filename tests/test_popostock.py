import gzip
import json

import popostock


def test_schema_is_namespaced():
    assert "popostock_instruments" in popostock.SCHEMA_SQL
    assert "popostock_candles" in popostock.SCHEMA_SQL
    assert "PRIMARY KEY (instrument_id, trade_date, timeframe)" in popostock.SCHEMA_SQL


def test_seed_is_readable_and_complete():
    with gzip.open(popostock.SEED_PATH, "rt", encoding="utf-8") as handle:
        seed = json.load(handle)
    assert seed["instrumentCount"] >= 60
    assert seed["candleCount"] >= 50_000
    symbols = {item["symbol"] for item in seed["instruments"]}
    assert {"TAIEX", "VIXTWN", "0050", "00981A", "ALI005"} <= symbols


def test_page_contains_popostock_routes():
    page = popostock.PAGE_PATH.read_text(encoding="utf-8")
    assert "/popostock/api/instruments" in page
    assert "/popostock/api/candles/" in page
    assert "Popostock" in page
