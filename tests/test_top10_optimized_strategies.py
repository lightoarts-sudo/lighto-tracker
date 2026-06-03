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


def make_top10_candles():
    candles = []
    for i in range(80):
        price = 100 + i * 0.01
        candles.append(candle(price, high=price + 0.05, low=price - 0.05, volume=100, t=i * 300_000))
    candles.append(candle(103.2, high=103.5, low=102.7, open_=102.8, volume=180, t=80 * 300_000))
    return candles


def test_top10_optimized_strategies_are_the_default_render_active_set():
    assert crypto_bot.CONFIG["microActiveStrategies"] == [
        "top10v1_rank5_chg3_10_sl1_trail09_t12",
        "top10v2_rank5_chg3_10_sl1_trail09_t18",
        "top10v3_rank5_chg3_10_sl08_trail09_t12",
        "top10v4_rank5_chg3_10_sl08_trail09_t18",
        "top10v5_delay1_rank3_chg1_5_sl15_trail12_t12",
    ]


def test_top10_optimized_signal_requires_current_1h_top10_rank_and_change_band():
    candles = make_top10_candles()
    sig = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000, "bidPx": "103.1", "askPx": "103.3"},
        candles,
        "top10v1_rank5_chg3_10_sl1_trail09_t12",
        rank_1h=5,
        collector_change_1h_pct=3.2,
    )
    assert sig["buy"] is True
    assert sig["strategy"] == "top10v1_rank5_chg3_10_sl1_trail09_t12"
    assert sig["reason"] == "top10v1_top10_entry"
    assert sig["rank1h"] == 5

    rank_too_low = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000},
        candles,
        "top10v1_rank5_chg3_10_sl1_trail09_t12",
        rank_1h=6,
        collector_change_1h_pct=3.2,
    )
    assert rank_too_low["buy"] is False

    too_cold = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000},
        candles,
        "top10v1_rank5_chg3_10_sl1_trail09_t12",
        rank_1h=3,
        collector_change_1h_pct=2.9,
    )
    assert too_cold["buy"] is False


def test_top10_optimized_exit_uses_variant_specific_stop_and_time_stop():
    state = {"avgEntry": 100.0, "assetQty": 1.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"time": 300_000, "lastLow": 99.1, "ma20": 100.0}
    assert crypto_bot.micro_top10_optimized_should_exit(signal, state, 99.1, "top10v3_rank5_chg3_10_sl08_trail09_t12")
    assert signal["exitReason"] == "top10v3_stop_loss_0_8pct"
    assert signal["exitPrice"] == 99.2

    state = {"avgEntry": 100.0, "assetQty": 1.0, "peakPrice": 100.3, "entryTime": 0}
    signal = {"time": 13 * 300_000, "lastLow": 100.0, "ma20": 100.0}
    assert crypto_bot.micro_top10_optimized_should_exit(signal, state, 100.1, "top10v5_delay1_rank3_chg1_5_sl15_trail12_t12")
    assert signal["exitReason"] == "top10v5_time_stop"
