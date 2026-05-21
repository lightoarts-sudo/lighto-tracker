import pathlib
import types


def load_report_module_without_running_job():
    path = pathlib.Path(__file__).resolve().parents[1] / "okx_micro_report_job.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace("\nwrite_state_and_report()\n", "\n")
    module = types.ModuleType("okx_micro_report_job_under_test")
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def make_row(close, *, high=None, low=None, ema9=99.0, ema21=96.2, ts=0):
    return {
        "close": close,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "ema9": ema9,
        "ema21": ema21,
        "high12_prev": 99.0,
        "low12_prev": 96.2,
        "vol_ratio": 1.3,
        "ts_iso": f"t{ts}",
    }


def test_report_backtest_caps_structural_stop_at_one_percent():
    job = load_report_module_without_running_job()
    rows = [make_row(98.0, ts=i) for i in range(25)]
    rows.append(make_row(100.0, high=100.5, low=99.5, ema9=99.2, ts=25))
    rows.append(make_row(95.0, high=100.2, low=95.0, ema9=98.0, ts=26))

    metrics, trades = job.backtest({"TEST-USDT": rows}, {"watchlist": ["TEST-USDT"]}, [])

    assert metrics["max_loss_pct"] >= -1.01
    assert trades[0]["pnl_pct"] == -1.0
    assert trades[0]["reason"] == "硬停損-1%"


def test_report_backtest_tp1_keeps_runner_instead_of_closing_entire_trade_at_1_2_percent():
    job = load_report_module_without_running_job()
    rows = [make_row(98.0, ts=i) for i in range(25)]
    rows.append(make_row(100.0, high=100.5, low=99.5, ema9=99.2, ts=25))
    rows.append(make_row(101.3, high=101.3, low=100.7, ema9=100.0, ema21=98.0, ts=26))
    rows.append(make_row(102.6, high=102.6, low=101.6, ema9=101.0, ema21=99.0, ts=27))

    _, trades = job.backtest({"TEST-USDT": rows}, {"watchlist": ["TEST-USDT"]}, [])

    assert trades[0]["reason"] == "TP2+尾倉續抱"
    assert trades[0]["pnl_pct"] > 1.2
