import importlib
import sys
import types


# The exit helpers are pure functions, but crypto_bot imports optional web/db
# dependencies at module import time. Stub them so strategy tests can run in the
# lightweight local test environment.
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


def make_signal(price=101.0, low=None, ma60=90.0, pct15=0.5, time=1_000_000):
    return {
        "lastLow": price if low is None else low,
        "ma60": ma60,
        "pct15": pct15,
        "time": time,
        "pre1hCandles": [],
        "volumeRatio": 1.0,
        "pct5": 0.0,
    }


def make_state(entry=100.0, qty=10.0):
    return {
        "avgEntry": entry,
        "assetQty": qty,
        "peakPrice": entry,
        "belowMa60Count": 0,
    }


def test_strategy1_hard_stop_caps_loss_at_one_percent_even_when_structure_stop_is_farther():
    state = make_state(entry=100.0)
    signal = make_signal(price=95.0, low=95.0)

    assert crypto_bot.micro_should_exit(signal, state, 95.0)

    assert signal["exitReason"] == "stop_loss_1pct"
    assert signal["exitPrice"] == 99.0
    assert signal["exitFraction"] == 1.0


def test_strategy1_first_take_profit_sells_half_and_moves_remaining_stop_to_breakeven():
    state = make_state(entry=100.0)
    signal = make_signal(price=101.2, low=100.8)

    assert crypto_bot.micro_should_exit(signal, state, 101.2)

    assert signal["exitReason"] == "tp1_take_half_move_stop_breakeven"
    assert signal["exitFraction"] == 0.5
    assert state["tp1Taken"] is True
    assert state["breakevenStopPrice"] == 100.2


def test_strategy1_after_tp1_breakeven_stop_prevents_winner_turning_into_loss():
    state = make_state(entry=100.0)
    state.update({"tp1Taken": True, "breakevenStopPrice": 100.2, "peakPrice": 101.2})
    signal = make_signal(price=99.8, low=99.8)

    assert crypto_bot.micro_should_exit(signal, state, 99.8)

    assert signal["exitReason"] == "breakeven_stop_after_tp1"
    assert signal["exitPrice"] == 100.2
    assert signal["exitFraction"] == 1.0


def test_rebuild_micro_stats_handles_partial_sells_as_one_closed_trade():
    rows = [
        {"strategy": "strategy1", "inst_id": "TEST-USDT", "side": "BUY", "price": 100.0, "quantity": 10.0, "quote_amount": 1000.0},
        {"strategy": "strategy1", "inst_id": "TEST-USDT", "side": "SELL", "price": 101.0, "quantity": 5.0, "quote_amount": 505.0},
        {"strategy": "strategy1", "inst_id": "TEST-USDT", "side": "SELL", "price": 100.2, "quantity": 5.0, "quote_amount": 501.0},
    ]

    stats = crypto_bot.rebuild_micro_stats(rows)

    item = stats[("strategy1", "TEST-USDT")]
    assert item["realizedPnl"] == 6.0
    assert item["closedTrades"] == 1
    assert item["wins"] == 1


def test_strategy2_trailing_starts_after_two_percent_gain_not_three():
    state = make_state(entry=100.0)
    state["peakPrice"] = 102.1
    signal = make_signal(price=101.0, low=101.0)

    assert crypto_bot.micro_strategy2_should_exit(signal, state, 101.0)

    assert signal["exitReason"] == "strategy2_trailing_giveback"
    assert signal["exitFraction"] == 1.0
