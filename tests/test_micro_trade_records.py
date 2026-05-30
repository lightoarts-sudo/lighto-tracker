import importlib
import pathlib
import sys
import types
from datetime import datetime, timezone, timedelta


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.modules.setdefault("asyncpg", types.SimpleNamespace())
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))
fastapi_stub = types.ModuleType("fastapi")
fastapi_stub.FastAPI = object
fastapi_stub.Query = lambda default=None, **kwargs: default
responses_stub = types.ModuleType("fastapi.responses")
responses_stub.HTMLResponse = lambda content=None, *args, **kwargs: content
responses_stub.JSONResponse = lambda content=None, *args, **kwargs: content
sys.modules.setdefault("fastapi", fastapi_stub)
sys.modules.setdefault("fastapi.responses", responses_stub)

crypto_bot = importlib.import_module("crypto_bot")


def row(id_, minutes, strategy, inst_id, side, price, qty=1.0, quote=100.0):
    return {
        "id": id_,
        "ts": datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        "strategy": strategy,
        "inst_id": inst_id,
        "side": side,
        "price": price,
        "quantity": qty,
        "quote_amount": quote,
    }


def test_build_micro_entry_exit_records_pairs_entry_exit_and_perf():
    rows = [
        row(2, 10, "strategy22", "ABC-USDT-SWAP", "SELL", 101.0),
        row(1, 0, "strategy22", "ABC-USDT-SWAP", "BUY", 100.0),
    ]

    records = crypto_bot.build_micro_entry_exit_records(rows)

    assert len(records) == 1
    assert records[0]["strategy"] == "strategy22"
    assert records[0]["inst_id"] == "ABC-USDT-SWAP"
    assert records[0]["entry_time"] == rows[1]["ts"]
    assert records[0]["exit_time"] == rows[0]["ts"]
    assert records[0]["pnl"] == 1.0
    assert records[0]["pnl_pct"] == 1.0
    assert records[0]["pnl_roe_pct"] == 5.0
    assert records[0]["status"] == "closed"


def test_build_micro_entry_exit_records_accumulates_partial_exits():
    rows = [
        row(1, 0, "strategy21", "XYZ-USDT-SWAP", "BUY", 100.0, qty=2.0, quote=200.0),
        row(2, 5, "strategy21", "XYZ-USDT-SWAP", "SELL", 101.0, qty=1.0, quote=101.0),
        row(3, 10, "strategy21", "XYZ-USDT-SWAP", "SELL", 102.0, qty=1.0, quote=102.0),
    ]

    records = crypto_bot.build_micro_entry_exit_records(rows)

    assert len(records) == 1
    assert records[0]["pnl"] == 3.0
    assert records[0]["pnl_pct"] == 1.5
    assert records[0]["pnl_roe_pct"] == 7.5
    assert records[0]["exit_time"] == rows[2]["ts"]


def test_summarize_micro_strategy_performance_12h_groups_by_strategy():
    records = crypto_bot.build_micro_entry_exit_records([
        row(1, 0, "strategy21", "AAA-USDT-SWAP", "BUY", 100.0),
        row(2, 10, "strategy21", "AAA-USDT-SWAP", "SELL", 101.0),
        row(3, 20, "strategy22", "BBB-USDT-SWAP", "BUY", 100.0),
    ])

    perf = crypto_bot.summarize_micro_strategy_performance_12h(
        records,
        datetime(2026, 5, 29, 23, 0, tzinfo=timezone.utc),
    )
    by_strategy = {item["strategy"]: item for item in perf}

    assert by_strategy["strategy21"]["entries"] == 1
    assert by_strategy["strategy21"]["closedTrades"] == 1
    assert by_strategy["strategy21"]["winRate"] == 100.0
    assert by_strategy["strategy22"]["entries"] == 1
    assert by_strategy["strategy22"]["openTrades"] == 1
