from micro_exit_optimizer import ExitParams, evaluate_params, rank_param_grid


def make_row(close, *, high=None, low=None, ema9=99.0, ema21=96.2, vol_ratio=1.3, ts=0):
    return {
        "close": close,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "ema9": ema9,
        "ema21": ema21,
        "high12_prev": 99.0,
        "low12_prev": 96.2,
        "vol_ratio": vol_ratio,
        "ts_ms": ts * 300_000,
        "ts_iso": f"t{ts}",
    }


def test_evaluate_params_caps_loss_and_keeps_trade_statistics():
    rows = [make_row(98.0, ts=i) for i in range(25)]
    rows.append(make_row(100.0, high=100.5, low=99.5, ema9=99.2, ts=25))
    rows.append(make_row(95.0, high=100.2, low=95.0, ema9=98.0, ts=26))

    result = evaluate_params({"TEST-USDT": rows}, ["TEST-USDT"], ExitParams(sl=1.0, tp1=1.0, tp2=2.0, be=0.2, trail_start=2.0, trail_giveback=1.0, time_stop_bars=6))

    assert result["trades"] == 1
    assert result["max_loss_pct"] == -1.0
    assert result["avg_return_pct"] == -1.0
    assert result["profit_factor"] == 0


def test_rank_param_grid_sorts_by_score_and_profit_factor():
    rows = [make_row(98.0, ts=i) for i in range(25)]
    rows.append(make_row(100.0, high=100.5, low=99.5, ema9=99.2, ts=25))
    rows.append(make_row(100.8, high=101.2, low=100.7, ema9=100.0, ema21=98.0, ts=26))
    rows.append(make_row(99.0, high=100.1, low=99.0, ema9=100.0, ema21=98.0, ts=27))

    results = rank_param_grid(
        {"TEST-USDT": rows},
        ["TEST-USDT"],
        {
            "sl": [1.0],
            "tp1": [1.0, 1.5],
            "tp2": [2.0],
            "be": [0.2],
            "trail_start": [2.0],
            "trail_giveback": [1.0],
            "time_stop_bars": [6],
        },
        min_trades=1,
        top=2,
    )

    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"]
    assert results[0]["params"]["tp1"] == 1.0
    assert results[0]["avg_return_pct"] > results[1]["avg_return_pct"]
