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


def make_strategy22_candles():
    candles = []
    for i in range(70):
        price = 99.2 + i * 0.01
        candles.append(candle(price, high=100.45, low=98.9, volume=100.0, t=i * 300_000))
    # This is the bar before the breakout bar. Its prior 1h high is about 100.45.
    candles.append(candle(100.35, high=100.4, low=99.7, open_=99.9, volume=100.0, t=70 * 300_000))
    # Previous bar breaks above the prior 1h high on >1.3x volume and above EMA9/EMA21.
    candles.append(candle(101.0, high=101.2, low=100.3, open_=100.55, volume=180.0, t=71 * 300_000))
    # Current bar retests the breakout level, holds it, and closes green without a hot 15m extension.
    candles.append(candle(100.88, high=101.05, low=100.55, open_=100.75, volume=90.0, t=72 * 300_000))
    return candles


def test_new_default_strategies_are_enabled_by_default():
    active = crypto_bot.CONFIG["microActiveStrategies"]
    expected = [
        "top10scan1_d1_r3_chg3_12_cur1_sl1_tr15x05_t12",
        "top10scan2_d1_r3_chg3_12_cur2_sl1_tr15x05_t12",
        "top10scan3_d1_r3_chg3_12_cur1_sl1_tr1x05_t12",
        "top10scan4_d1_r3_chg3_12_cur2_sl1_tr1x05_t12",
        "top10scan5_d1_r3_chg2_12_cur2_sl1_tr15x05_t12",
        "top10shadow1_d0_r5_chg2_15_cur0_sl1_tr1x05_t12",
        "top10shadow2_d0_r10_chg1_20_cur0_sl12_tr15x06_t12",
        "top10shadow3_d1_r5_chg1_12_cur0_vol08_sl1_tr1x05_t18",
        "top5dplus_score95_chg2_5_sl1_tr06x03_t6",
        "top10live1_d3_r3_chg1-12_green_vol1.5_sl1.0_be0.6_tr0.9x0.4_t12",
        "top10live2_d3_r3_chg1-12_green_vol1.5_sl1.5_be0.6_tr0.9x0.4_t12",
        "top10live3_d3_r3_chg1-12_green_vol1.5_sl2.0_be0.6_tr0.9x0.4_t12",
    ]
    assert active == expected
    for strategy in expected:
        assert crypto_bot.micro_strategy_enabled(strategy)
    
    # Old top10scan strategies no longer in active set
    assert not crypto_bot.micro_strategy_enabled("top10scan_d2_r5_chg2-8_cur2_vol1.2_sl0.8_tr1.5x0.5_t12")
    assert not crypto_bot.micro_strategy_enabled("top10scan_d1_r3_chg3-12_cur1_vol0_sl1_tr1.5x0.5_t12")
    assert not crypto_bot.micro_strategy_enabled("top10scan_d1_r3_chg3-12_cur2_vol0_sl1_tr1.5x0.5_t12")
    assert not crypto_bot.micro_strategy_enabled("top10scan_d2_r5_chg2-8_cur2_vol1.2_sl1_tr1.5x0.5_t12")
    assert not crypto_bot.micro_strategy_enabled("top10scan_d1_r3_chg3-12_cur1_vol0_sl1_tr1x0.5_t12")


def test_strategy22_uses_tighter_shadow_watchlist_defaults():
    assert crypto_bot.CONFIG["microStrategy22TopN"] == 10
    assert crypto_bot.CONFIG["microStrategy22MinPct2h"] == 1.2
    assert crypto_bot.CONFIG["microStrategy22MinPct3h"] == 0.0
    assert crypto_bot.CONFIG["microStrategy22MaxPct1h"] == 2.0
    assert crypto_bot.CONFIG["microStrategy22MaxPct15m"] == 1.4


def test_strategy22_enters_on_2h_strength_breakout_retest_and_records_slippage():
    signal = crypto_bot.micro_strategy22_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 0, "_quoteVol": 1_000_000, "bidPx": "100.95", "askPx": "101.15"},
        make_strategy22_candles(),
    )

    assert signal["buy"] is True
    assert signal["strategy"] == "strategy22_2h_strength_breakout_retest"
    assert signal["reason"] == "strategy22_2h_breakout_retest"
    assert signal["strategy22PrevBreakout"] is True
    assert signal["strategy22Retest"] is True
    assert signal["spreadPct"] > 0
    assert "buySlippagePct" in signal
    assert "sellSlippagePct" in signal


def test_strategy22_uses_lab_exit_stop_parameter():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.25, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy22_should_exit(signal, state, 99.25)

    assert signal["exitReason"] == "strategy22_stop_loss_0_7pct"
    assert signal["exitPrice"] == 99.3
    assert signal["exitFraction"] == 1.0
