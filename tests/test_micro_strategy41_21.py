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


def make_strategy41_candles(stretched=False):
    candles = []
    for i in range(70):
        price = 100.0 + i * 0.02
        candles.append(candle(price, high=102.4, low=99.8, volume=100.0, t=i * 300_000))
    candles.append(candle(102.6, high=102.8, low=101.8, open_=102.2, volume=180.0, t=70 * 300_000))
    if stretched:
        candles.append(candle(104.4, high=104.6, low=102.4, open_=102.8, volume=140.0, t=71 * 300_000))
    else:
        candles.append(candle(102.9, high=103.0, low=102.45, open_=102.65, volume=140.0, t=71 * 300_000))
    return candles


def strategy21_signal(**overrides):
    base = {
        "instId": "TEST-USDT-SWAP",
        "price": 101.0,
        "lastLow": 100.8,
        "pct15": 0.5,
        "pct1h": 2.0,
        "volumeRatio": 1.5,
        "distanceMa60Pct": 1.0,
        "ma20": 100.0,
        "ma60": 99.0,
        "ma60Slope": 0.1,
        "notOverextended": True,
        "chaseRisk": False,
        "time": 300_000,
        "bidPx": 100.9,
        "askPx": 101.1,
    }
    base.update(overrides)
    return base


def test_strategy41_and_21_are_enabled_by_default():
    assert crypto_bot.micro_strategy_enabled("strategy4.1_breakout_confirmation")
    assert crypto_bot.micro_strategy_enabled("strategy2.1_surge_momentum")


def test_strategy41_confirms_breakout_but_rejects_overstretched_follow_through():
    ok = crypto_bot.micro_strategy41_signal({"instId": "TEST-USDT-SWAP", "_pct24": 0, "_quoteVol": 1_000_000, "bidPx": 102.85, "askPx": 102.95}, make_strategy41_candles())
    stretched = crypto_bot.micro_strategy41_signal({"instId": "TEST-USDT-SWAP", "_pct24": 0, "_quoteVol": 1_000_000, "bidPx": 104.35, "askPx": 104.45}, make_strategy41_candles(stretched=True))

    assert ok["buy"] is True
    assert ok["strategy"] == "strategy4.1_breakout_confirmation"
    assert ok["reason"] == "strategy4.1_confirmed_breakout_filtered"
    assert stretched["buy"] is False
    assert stretched["strategy41StructureOk"] is False


def test_strategy21_surge_filters_heat_and_spread_before_entry():
    ok = crypto_bot.micro_strategy21_surge_signal(strategy21_signal())
    too_hot = crypto_bot.micro_strategy21_surge_signal(strategy21_signal(pct1h=8.0))
    wide_spread = crypto_bot.micro_strategy21_surge_signal(strategy21_signal(bidPx=100.0, askPx=101.0))

    assert ok["buy"] is True
    assert ok["reason"] == "strategy2.1_filtered_surge_momentum"
    assert too_hot["buy"] is False
    assert too_hot["strategy21SurgeHeatOk"] is False
    assert wide_spread["buy"] is False
    assert wide_spread["strategy21SurgeSpreadOk"] is False


def test_strategy21_surge_uses_tighter_stop_loss():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = strategy21_signal(lastLow=99.2, time=300_000)

    assert crypto_bot.micro_strategy21_surge_should_exit(signal, state, 99.2)
    assert signal["exitReason"] == "strategy2.1_stop_loss_0_7pct"
    assert signal["exitPrice"] == 99.3
    assert signal["exitFraction"] == 1.0
