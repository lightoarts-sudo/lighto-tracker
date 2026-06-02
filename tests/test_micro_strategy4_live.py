import importlib
import pathlib
import sys
import types


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


def candle(close, high=None, low=None, open_=None, volume=100.0, t=0):
    return {
        "open": close if open_ is None else open_,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": volume,
        "closeTime": t,
    }


def make_strategy4_candles():
    candles = []
    # Stable base volume/price history so EMA9 > EMA21 on the breakout bar and
    # the prior 1h return can be measured.
    for i in range(70):
        price = 100.0 + i * 0.02
        candles.append(candle(price, high=100.8, low=99.8, volume=100.0, t=i * 300_000))
    # Previous bar is the breakout over the earlier 1h high, with volume >= 1.4x.
    candles.append(candle(103.0, high=103.2, low=101.2, open_=101.4, volume=180.0, t=70 * 300_000))
    # Current confirmation bar holds the breakout level and closes 0.2% above the breakout close.
    candles.append(candle(103.3, high=103.5, low=101.0, open_=103.05, volume=140.0, t=71 * 300_000))
    return candles


def test_strategy4_breakout_confirmation_is_enabled_by_default():
    assert crypto_bot.micro_strategy_enabled("strategy4.1_breakout_confirmation")


def test_strategy4_enters_only_after_breakout_bar_is_confirmed_by_next_bar():
    signal = crypto_bot.micro_strategy4_signal({"instId": "TEST-USDT-SWAP", "_pct24": 0, "_quoteVol": 1_000_000}, make_strategy4_candles())

    assert signal["buy"] is True
    assert signal["strategy"] == "strategy4_breakout_confirmation"
    assert signal["reason"] == "strategy4_confirmed_breakout"
    assert signal["strategy4PrevBreakout"] is True
    assert signal["strategy4Hold"] is True


def test_strategy4_uses_optimized_exit_parameters_from_lab():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.1, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy4_should_exit(signal, state, 99.1)

    assert signal["exitReason"] == "strategy4_stop_loss_0_8pct"
    assert signal["exitPrice"] == 99.2
    assert signal["exitFraction"] == 1.0
