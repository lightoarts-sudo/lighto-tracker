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
        "top10scan1_d1_r3_chg3_12_cur1_sl1_tr15x05_t12",
        "top10scan2_d1_r3_chg3_12_cur2_sl1_tr15x05_t12",
        "top10scan3_d1_r3_chg3_12_cur1_sl1_tr1x05_t12",
        "top10scan4_d1_r3_chg3_12_cur2_sl1_tr1x05_t12",
        "top10scan6_d1_r3_chg3_12_cur1_sl08_tr15x05_t12",
    ]


def test_top10_scan6_matches_today_optimizer_fifth_candidate_params():
    params = crypto_bot.MICRO_TOP10_OPTIMIZED_STRATEGIES["top10scan6_d1_r3_chg3_12_cur1_sl08_tr15x05_t12"]
    assert params["entry_delay_bars"] == 1
    assert params["max_rank"] == 3
    assert params["min_change_1h_pct"] == 3.0
    assert params["max_change_1h_pct"] == 12.0
    assert params["min_current_change_1h_pct"] == 1.0
    assert params["require_change_reclaim"] is True
    assert params["stop_loss_pct"] == 0.8
    assert params["trailing_start_pct"] == 1.5
    assert params["trailing_giveback_pct"] == 0.5
    assert params["time_stop_bars"] == 12


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


def test_top10_scan_signal_requires_delay_current_reclaim_and_volume_filters():
    candles = make_top10_candles()
    strategy = "top10scan1_d1_r3_chg3_12_cur1_sl1_tr15x05_t12"

    too_early = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000},
        candles,
        strategy,
        rank_1h=3,
        collector_change_1h_pct=3.2,
        session_age_bars=0,
    )
    assert too_early["buy"] is False
    assert too_early["top10DelayOk"] is False

    reclaimed = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000, "bidPx": "103.1", "askPx": "103.3"},
        candles,
        strategy,
        rank_1h=3,
        collector_change_1h_pct=3.2,
        session_age_bars=1,
    )
    assert reclaimed["buy"] is True
    assert reclaimed["top10CurrentChangeOk"] is True
    assert reclaimed["top10ReclaimOk"] is True

    failed_reclaim = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000},
        candles,
        strategy,
        rank_1h=3,
        collector_change_1h_pct=5.0,
        session_age_bars=1,
    )
    assert failed_reclaim["buy"] is False
    assert failed_reclaim["top10ReclaimOk"] is False

    volume_strategy = "top10scan1v_d1_r3_chg3_12_cur1_vol12_sl1_tr15x05_t12"
    low_volume = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000},
        candles,
        volume_strategy,
        rank_1h=3,
        collector_change_1h_pct=3.2,
        session_age_bars=1,
    )
    assert low_volume["buy"] is False
    assert low_volume["top10VolumeOk"] is False


def test_top10_shadow_strategy_is_looser_but_marked_shadow_only():
    candles = make_top10_candles()
    strategy = "top10shadow1_d0_r5_chg2_15_cur0_sl1_tr1x05_t12"
    assert crypto_bot.MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy]["shadow_only"] is True

    signal = crypto_bot.micro_top10_optimized_signal(
        {"instId": "TEST-USDT-SWAP", "_quoteVol": 1_000_000, "bidPx": "103.1", "askPx": "103.3"},
        candles,
        strategy,
        rank_1h=5,
        collector_change_1h_pct=2.2,
        session_age_bars=0,
    )

    assert signal["buy"] is True
    assert signal["reason"] == "top10shadow1_top10_entry"
    assert signal["top10DelayOk"] is True
    assert signal["top10ReclaimOk"] is True


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
