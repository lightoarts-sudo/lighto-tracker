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


def test_strategy9_18_20_21_and_23_enabled_by_default():
    assert crypto_bot.micro_strategy_enabled("strategy9_ema9_bounce_low_heat")
    assert crypto_bot.micro_strategy_enabled("s18_top2h_retest_runner")
    assert crypto_bot.micro_strategy_enabled("strategy20_6h12h_cool_vwap_reclaim")
    assert crypto_bot.micro_strategy_enabled("strategy21_multi_tf_intersection_ema9_bounce")
    assert crypto_bot.micro_strategy_enabled("strategy23_top1h_clean_early_breakout")


def make_strategy20_candles():
    candles = []
    for i in range(70):
        candles.append(candle(100.0, high=100.2, low=99.8, volume=100.0, t=i * 300_000))
    for i in range(70, 144):
        price = 100.0 + (i - 70) * 0.095
        candles.append(candle(price, high=price * 1.001, low=price * 0.999, open_=price * 0.9995, volume=100.0, t=i * 300_000))
    # Previous bar cools into EMA21/VWAP support.
    candles.append(candle(106.7, high=107.2, low=106.2, open_=106.9, volume=100.0, t=144 * 300_000))
    # Current bar reclaims EMA9 and VWAP with controlled 15m/1h extension.
    candles.append(candle(107.3, high=107.55, low=106.8, open_=106.85, volume=120.0, t=145 * 300_000))
    return candles


def test_strategy20_enters_on_6h12h_cool_vwap_reclaim(monkeypatch):
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy20MaxPct15m", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy20ReclaimBufferPct", 1.0)
    signal = crypto_bot.micro_strategy20_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 8, "_quoteVol": 1_000_000, "bidPx": "107.2", "askPx": "107.4"},
        make_strategy20_candles(),
    )

    assert signal["strategy"] == "strategy20_6h12h_cool_vwap_reclaim"
    assert signal["buy"] is True
    assert signal["strategy20TrendFilter"] is True
    assert signal["strategy20ReclaimFilter"] is True



def make_strategy21_candles():
    candles = []
    for i in range(90):
        candles.append(candle(100.0, high=100.2, low=99.8, volume=100.0, t=i * 300_000))
    for i in range(90, 133):
        price = 100.0 + (i - 90) * 0.09
        candles.append(candle(price, high=price * 1.001, low=price * 0.999, open_=price * 0.9995, volume=100.0, t=i * 300_000))
    # Previous bar pulls back into EMA9 support while staying above EMA21.
    candles.append(candle(103.75, high=104.1, low=103.4, open_=103.9, volume=100.0, t=133 * 300_000))
    # Current bar reclaims EMA9 with a green body and controlled 15m/1h extension.
    candles.append(candle(104.45, high=104.55, low=103.7, open_=104.0, volume=120.0, t=134 * 300_000))
    for i in range(135, 147):
        price = 104.45 + (i - 134) * 0.01
        candles.append(candle(price, high=price * 1.001, low=price * 0.999, open_=price * 0.9995, volume=100.0, t=i * 300_000))
    return candles


def test_strategy21_enters_on_multi_tf_ema9_bounce(monkeypatch):
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy21MaxPct15m", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy21MinPct3h", 2.5)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy21Ema9TouchPct", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy21MinBodyPct", -0.1)
    signal = crypto_bot.micro_strategy21_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 5, "_quoteVol": 1_000_000, "bidPx": "104.4", "askPx": "104.5"},
        make_strategy21_candles(),
    )

    assert signal["strategy"] == "strategy21_multi_tf_intersection_ema9_bounce"
    assert signal["buy"] is True
    assert signal["strategy21TrendFilter"] is True
    assert signal["strategy21BounceFilter"] is True


def make_strategy9_candles():
    candles = []
    for i in range(60):
        candles.append(candle(100.0, high=100.2, low=99.8, volume=100.0, t=i * 300_000))
    for i in range(60, 72):
        price = 100.0 + (i - 60) * 0.06
        candles.append(candle(price, high=price * 1.001, low=price * 0.999, open_=price * 0.9995, volume=100.0, t=i * 300_000))
    candles.append(candle(100.55, high=100.9, low=100.05, open_=100.7, volume=100.0, t=72 * 300_000))
    candles.append(candle(100.95, high=101.05, low=100.45, open_=100.65, volume=120.0, t=73 * 300_000))
    return candles


def test_strategy9_enters_on_ema9_bounce_low_heat(monkeypatch):
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy9MinPct1h", 0.2)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy9MaxPct1h", 2.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy9MaxPct15m", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy9Ema9TouchPct", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy9MinVolumeRatio", 0.5)
    signal = crypto_bot.micro_strategy9_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 3, "_quoteVol": 1_000_000, "bidPx": "100.9", "askPx": "101.0"},
        make_strategy9_candles(),
    )

    assert signal["strategy"] == "strategy9_ema9_bounce_low_heat"
    assert signal["buy"] is True
    assert signal["strategy9TrendFilter"] is True
    assert signal["strategy9BounceFilter"] is True


def make_strategy18_candles():
    candles = []
    for i in range(60):
        candles.append(candle(100.0, high=100.15, low=99.85, volume=100.0, t=i * 300_000))
    for i in range(60, 72):
        price = 100.0 + (i - 60) * 0.08
        candles.append(candle(price, high=price * 1.002, low=price * 0.998, open_=price * 0.999, volume=100.0, t=i * 300_000))
    # Previous candle breaks the prior 1H range with enough volume.
    candles.append(candle(101.25, high=101.35, low=100.7, open_=100.85, volume=160.0, t=72 * 300_000))
    # Current candle retests the breakout area, holds it, and reclaims EMA9.
    candles.append(candle(101.45, high=101.6, low=101.0, open_=101.1, volume=120.0, t=73 * 300_000))
    return candles


def test_strategy18_enters_on_top2h_breakout_retest(monkeypatch):
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18MinPct2h", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18MaxPct1h", 3.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18MaxPct15m", 1.0)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18BreakVolumeRatio", 1.1)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18ConfirmVolumeRatio", 0.5)
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy18RetestTolerancePct", 0.8)
    signal = crypto_bot.micro_strategy18_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 4, "_quoteVol": 1_000_000, "bidPx": "101.4", "askPx": "101.5"},
        make_strategy18_candles(),
    )

    assert signal["strategy"] == "s18_top2h_retest_runner"
    assert signal["buy"] is True
    assert signal["strategy18PrevBreakout"] is True
    assert signal["strategy18Retest"] is True


def make_strategy23_candles():
    candles = []
    for i in range(60):
        candles.append(candle(99.6, high=100.0, low=99.2, volume=100.0, t=i * 300_000))
    for i in range(60, 72):
        price = 99.8 + (i - 60) * 0.08
        candles.append(candle(price, high=101.0, low=price * 0.997, volume=220.0, t=i * 300_000))
    candles.append(candle(101.55, high=101.7, low=100.95, open_=101.2, volume=220.0, t=72 * 300_000))
    return candles


def test_strategy23_enters_on_clean_top1h_breakout(monkeypatch):
    monkeypatch.setitem(crypto_bot.CONFIG, "microStrategy23MaxPct15m", 1.1)
    signal = crypto_bot.micro_strategy23_signal(
        {"instId": "TEST-USDT-SWAP", "_pct24": 4, "_quoteVol": 1_000_000, "bidPx": "101.5", "askPx": "101.6"},
        make_strategy23_candles(),
    )

    assert signal["strategy"] == "strategy23_top1h_clean_early_breakout"
    assert signal["buy"] is True
    assert signal["strategy23TrendFilter"] is True
    assert signal["strategy23BreakoutFilter"] is True


def test_strategy20_uses_lab_exit_stop_parameter():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.25, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy20_should_exit(signal, state, 99.25)
    assert signal["exitReason"] == "strategy20_stop_loss_0_7pct"
    assert signal["exitPrice"] == 99.3
    assert signal["exitFraction"] == 1.0



def test_strategy21_uses_lab_exit_stop_parameter():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.35, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy21_should_exit(signal, state, 99.35)
    assert signal["exitReason"] == "strategy21_stop_loss_0_6pct"
    assert signal["exitPrice"] == 99.4
    assert signal["exitFraction"] == 1.0


def test_strategy9_uses_lab_exit_stop_parameter():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.25, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy9_should_exit(signal, state, 99.25)
    assert signal["exitReason"] == "strategy9_stop_loss_0_7pct"
    assert signal["exitPrice"] == 99.3


def test_strategy18_uses_lab_exit_stop_parameter():
    state = {"avgEntry": 100.0, "assetQty": 10.0, "peakPrice": 100.0, "entryTime": 0}
    signal = {"lastLow": 99.35, "pct15": 0.0, "time": 300_000, "ma20": 100.0}

    assert crypto_bot.micro_strategy18_should_exit(signal, state, 99.35)
    assert signal["exitReason"] == "strategy18_stop_loss_0_6pct"
    assert signal["exitPrice"] == 99.4
