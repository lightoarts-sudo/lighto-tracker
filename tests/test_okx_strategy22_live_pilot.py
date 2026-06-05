import base64
import hashlib
import hmac

import pytest

from okx_strategy22_live_pilot import (
    build_long_stop_loss_algo_payload,
    calc_long_stop_loss_price,
    calc_swap_order_size,
    floor_to_step,
    format_size,
    is_no_position_reduce_error,
    okx_position_contract_size,
    sign_okx,
    slippage_pct,
    guarded_entry_reject_reason,
    record_instrument_trade_outcome,
    should_pause_for_global_loss,
    parse_args,
)


def test_okx_signature_matches_manual_hmac():
    ts = "2026-05-31T00:00:00.000Z"
    method = "POST"
    path = "/api/v5/trade/order"
    body = '{"instId":"ABC-USDT-SWAP","tdMode":"isolated","side":"buy","ordType":"market","sz":"1"}'
    secret = "secret"
    expected = base64.b64encode(hmac.new(secret.encode(), f"{ts}{method}{path}{body}".encode(), hashlib.sha256).digest()).decode()
    assert sign_okx(ts, method, path, body, secret) == expected


def test_swap_order_size_rounds_down_to_lot_size():
    sz, meta = calc_swap_order_size(2.0, 0.5, {"instId": "ABC-USDT-SWAP", "ctVal": "1", "lotSz": "0.1", "minSz": "0.1"})
    assert sz == "4.0"
    assert meta["roundedSz"] == pytest.approx(4.0)


def test_swap_order_size_rejects_too_small_notional():
    with pytest.raises(ValueError, match="below minimum"):
        calc_swap_order_size(2.0, 100.0, {"instId": "ABC-USDT-SWAP", "ctVal": "1", "lotSz": "1", "minSz": "1"})


def test_step_formatting():
    assert floor_to_step(1.239, 0.01) == pytest.approx(1.23)
    assert format_size(1.2, 0.1) == "1.2"
    assert format_size(2.0, 1.0) == "2"


def test_slippage_signs_are_adverse_positive():
    assert slippage_pct("buy", 100, 101) == pytest.approx(1.0)
    assert slippage_pct("sell", 100, 99) == pytest.approx(1.0)
    assert slippage_pct("sell", 100, 101) == pytest.approx(-1.0)


def test_calc_long_stop_loss_price_defaults_to_one_percent_below_entry():
    assert calc_long_stop_loss_price(100.0, 1.0) == pytest.approx(99.0)
    assert calc_long_stop_loss_price(0.012345, 1.0) == pytest.approx(0.01222155)


def test_build_long_stop_loss_algo_payload_uses_okx_native_market_stop():
    payload = build_long_stop_loss_algo_payload("ABC-USDT-SWAP", "isolated", "4.0", 99.0)
    assert payload == {
        "instId": "ABC-USDT-SWAP",
        "tdMode": "isolated",
        "side": "sell",
        "ordType": "conditional",
        "sz": "4.0",
        "slTriggerPx": "99",
        "slOrdPx": "-1",
        "slTriggerPxType": "last",
        "reduceOnly": "true",
    }


def test_is_no_position_reduce_error_detects_okx_51169():
    err = RuntimeError("OKX private API error POST /api/v5/trade/order: {'sCode': '51169', 'sMsg': \"Order failed because you don't have any positions in this direction for this contract to reduce or close. \"}")
    assert is_no_position_reduce_error(err)
    assert not is_no_position_reduce_error(RuntimeError("different OKX error"))


def test_okx_position_contract_size_reads_flat_and_open_positions():
    rows = [
        {"instId": "ABC-USDT-SWAP", "pos": "0"},
        {"instId": "XYZ-USDT-SWAP", "pos": "-3"},
    ]
    assert okx_position_contract_size(rows, "ABC-USDT-SWAP") == 0.0
    assert okx_position_contract_size(rows, "XYZ-USDT-SWAP") == 3.0
    assert okx_position_contract_size(rows, "MISSING-USDT-SWAP") == 0.0


def test_guarded_entry_rejects_weak_momentum_and_bad_liquidity():
    base = {"pct1h": 4.0, "pct2h": 1.0, "pct3h": 1.0, "pct15": 0.6, "volumeRatio": 1.6, "spreadPct": 0.04, "buySlippagePct": 0.1}
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", base, {}, "2026-06-04T00:00:00+00:00") is None
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", {**base, "pct15": -0.1}, {}, "2026-06-04T00:00:00+00:00") == "weak_pct15"
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", {**base, "volumeRatio": 0.9}, {}, "2026-06-04T00:00:00+00:00") == "weak_volume"
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", {**base, "pct2h": -0.1}, {}, "2026-06-04T00:00:00+00:00") == "negative_pct2h"
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", {**base, "pct3h": -0.1}, {}, "2026-06-04T00:00:00+00:00") == "negative_pct3h"
    assert guarded_entry_reject_reason("ABC-USDT-SWAP", {**base, "spreadPct": 0.2}, {}, "2026-06-04T00:00:00+00:00") == "wide_spread"


def test_record_trade_outcome_enforces_cooldown_and_blacklist_after_repeated_losses():
    state = {"risk": {}}
    first = "2026-06-04T01:00:00+00:00"
    second = "2026-06-04T02:00:00+00:00"
    signal = {"pct1h": 4.0, "pct2h": 1.0, "pct3h": 1.0, "pct15": 0.6, "volumeRatio": 1.6, "spreadPct": 0.04, "buySlippagePct": 0.1}

    record_instrument_trade_outcome(state, "OPN-USDT-SWAP", -0.08, first)
    assert guarded_entry_reject_reason("OPN-USDT-SWAP", signal, state, "2026-06-04T02:30:00+00:00") == "cooldown_after_loss"

    record_instrument_trade_outcome(state, "OPN-USDT-SWAP", -0.09, second)
    assert guarded_entry_reject_reason("OPN-USDT-SWAP", signal, state, "2026-06-04T05:30:00+00:00") == "instrument_blacklisted"


def test_global_loss_guard_pauses_after_loss_or_loss_streak():
    state = {"risk": {}}
    for i in range(5):
        record_instrument_trade_outcome(state, f"LOSS{i}-USDT-SWAP", -0.05, f"2026-06-04T0{i}:00:00+00:00")
    assert should_pause_for_global_loss(state, "2026-06-04T05:00:00+00:00") == "consecutive_loss_limit"

    state = {"risk": {}}
    for i in range(4):
        record_instrument_trade_outcome(state, f"BIG{i}-USDT-SWAP", -0.26, f"2026-06-04T0{i}:00:00+00:00")
    assert should_pause_for_global_loss(state, "2026-06-04T05:00:00+00:00") == "daily_loss_limit"


def test_live_unlimited_requires_explicit_override(monkeypatch):
    monkeypatch.setenv("OKX_TOP10_PILOT_LIVE", "1")
    monkeypatch.setattr("sys.argv", ["okx_strategy22_live_pilot.py", "--i-understand-live-trading", "--max-entries", "0"])
    with pytest.raises(SystemExit, match="refuses unlimited entries"):
        parse_args()

    monkeypatch.setattr("sys.argv", ["okx_strategy22_live_pilot.py", "--i-understand-live-trading", "--max-entries", "0", "--allow-unlimited-live"])
    assert parse_args().max_entries == 0
