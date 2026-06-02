import pytest

import crypto_bot


def test_okx_live_performance_pairs_log_trades_and_summarizes_strategy():
    rows = [
        {"ts": "2026-06-01T00:00:00+00:00", "event": "start", "marginUSDT": 2.0, "leverage": 5.0},
        {
            "ts": "2026-06-01T00:01:00+00:00",
            "event": "BUY",
            "instId": "ABC-USDT-SWAP",
            "orderId": "buy1",
            "sz": "4",
            "sizing": {"ctVal": 10, "roundedSz": 4},
            "fillPrice": 0.25,
            "hardStopAlgoId": "algo1",
            "hardStopPrice": 0.2475,
            "signal": {"strategy": "strategy22_2h_strength_breakout_retest", "reason": "entry"},
        },
        {
            "ts": "2026-06-01T00:06:00+00:00",
            "event": "SELL",
            "instId": "ABC-USDT-SWAP",
            "orderId": "sell1",
            "sz": "4",
            "fillPrice": 0.255,
            "realizedPnl": 0.2,
            "reason": "tp",
        },
        {
            "ts": "2026-06-01T00:07:00+00:00",
            "event": "BUY",
            "instId": "DEF-USDT-SWAP",
            "orderId": "buy2",
            "sz": "2",
            "sizing": {"ctVal": 10, "roundedSz": 2},
            "fillPrice": 1.0,
            "hardStopAlgoId": "algo2",
            "signal": {"reason": "entry"},
        },
    ]

    payload = crypto_bot.summarize_okx_live_performance(rows)

    assert payload["summary"]["closedTrades"] == 1
    assert payload["summary"]["openPositions"] == 1
    assert payload["summary"]["wins"] == 1
    assert payload["summary"]["winRate"] == pytest.approx(100.0)
    assert payload["summary"]["pnlUsd"] == pytest.approx(0.2)
    assert payload["summary"]["pnlPct"] == pytest.approx(10.0)
    assert payload["summary"]["hardStopProtectedBuys"] == 2
    assert payload["closedTrades"][0]["instId"] == "ABC-USDT-SWAP"
    assert payload["closedTrades"][0]["pnlPct"] == pytest.approx(10.0)
    assert payload["openPositions"][0]["instId"] == "DEF-USDT-SWAP"
    assert payload["byStrategy"][0]["strategy"] == "strategy22_2h_strength_breakout_retest"


def test_okx_live_performance_counts_losing_trade_in_win_rate():
    rows = [
        {"ts": "2026-06-01T00:00:00+00:00", "event": "start", "marginUSDT": 2.0},
        {"ts": "2026-06-01T00:01:00+00:00", "event": "BUY", "instId": "ABC-USDT-SWAP", "fillPrice": 1, "sz": "1", "sizing": {"ctVal": 1}},
        {"ts": "2026-06-01T00:02:00+00:00", "event": "SELL", "instId": "ABC-USDT-SWAP", "fillPrice": 0.99, "realizedPnl": -0.1},
    ]
    payload = crypto_bot.summarize_okx_live_performance(rows)
    assert payload["summary"]["wins"] == 0
    assert payload["summary"]["losses"] == 1
    assert payload["summary"]["winRate"] == 0
    assert payload["summary"]["pnlPct"] == pytest.approx(-5.0)
