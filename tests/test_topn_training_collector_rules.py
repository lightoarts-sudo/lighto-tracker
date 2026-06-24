import sqlite3
from pathlib import Path

import okx_top10_1h_training_collector as collector


def make_candles(base=100.0, change_pct=1.0, start=1_700_000_000_000, n=20):
    rows = []
    # Make rows[-13] the 1H base and rows[-1] the latest close.
    for i in range(n):
        close = base
        if i == n - 13:
            close = base
        elif i == n - 1:
            close = base * (1 + change_pct / 100.0)
        else:
            close = base * (1 + change_pct / 100.0 * i / max(n - 1, 1))
        rows.append(
            {
                "ts_ms": start + i * 300_000,
                "ts_iso": f"t{i}",
                "open": close * 0.999,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "vol": 100 + i,
                "vol_ccy": 1000 + i,
            }
        )
    return rows


def install_fake_market(monkeypatch, changes):
    universe = [
        {"inst_id": f"C{i}-USDT", "base_ccy": f"C{i}", "quote_vol_24h": 10_000 - i, "ticker_last": 1.0}
        for i in range(1, len(changes) + 1)
    ]
    candles = {item["inst_id"]: make_candles(base=100 + i, change_pct=chg) for i, (item, chg) in enumerate(zip(universe, changes), 1)}
    monkeypatch.setattr(collector, "fetch_universe", lambda max_universe: universe)
    monkeypatch.setattr(collector, "fetch_5m", lambda inst_id, limit=20: candles[inst_id])
    monkeypatch.setattr(collector, "now_taipei", lambda: collector.datetime(2026, 6, 23, 12, 0, tzinfo=collector.TZ))
    return candles


def test_collector_opens_research_top20_sessions_and_marks_top5_signal(tmp_path, monkeypatch):
    db = tmp_path / "training.sqlite"
    # Descending positive 1H changes: all 20 should become research sessions.
    install_fake_market(monkeypatch, [21 - i for i in range(1, 21)])

    result = collector.collect_once(db, max_universe=220, sleep_s=0, max_rank=20, entry_rank=5)

    assert result["opened"] == [f"C{i}-USDT" for i in range(1, 21)]
    assert len(result["topn"]) == 20
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    sessions = con.execute("SELECT inst_id, entry_rank_1h, entry_is_signal_top5, entry_signal_rank FROM top10_1h_training_sessions ORDER BY entry_rank_1h").fetchall()
    assert len(sessions) == 20
    assert [row["entry_is_signal_top5"] for row in sessions[:5]] == [1, 1, 1, 1, 1]
    assert [row["entry_signal_rank"] for row in sessions[:5]] == [1, 2, 3, 4, 5]
    assert all(row["entry_is_signal_top5"] == 0 for row in sessions[5:])
    assert all(row["entry_signal_rank"] is None for row in sessions[5:])


def test_negative_change_records_final_candle_and_keeps_post_exit_collection(tmp_path, monkeypatch):
    db = tmp_path / "training.sqlite"
    install_fake_market(monkeypatch, [10, 9, 8, 7, 6])
    collector.collect_once(db, max_universe=220, sleep_s=0, max_rank=20, entry_rank=5, post_exit_bars=12)

    # Same coin remains in ranked universe but turns negative: final negative candle should be saved,
    # exit_reason is set, and collection remains active for post-exit bars.
    install_fake_market(monkeypatch, [-1, 4, 3, 2, 1])
    result = collector.collect_once(db, max_universe=220, sleep_s=0, max_rank=20, entry_rank=5, post_exit_bars=12)

    assert "C1-USDT" in result["closed"]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    sess = con.execute("SELECT * FROM top10_1h_training_sessions WHERE inst_id='C1-USDT'").fetchone()
    assert sess["exit_reason"] == "change_below_zero"
    assert sess["is_active"] == 1
    assert sess["post_exit_bars_remaining"] == 11
    assert sess["last_change_1h_pct"] < 0
    neg_candle_count = con.execute(
        "SELECT COUNT(*) FROM top10_1h_training_candles WHERE session_id=? AND change_1h_pct < 0",
        (sess["id"],),
    ).fetchone()[0]
    assert neg_candle_count >= 1


def test_left_liquidity_universe_has_specific_exit_reason(tmp_path, monkeypatch):
    db = tmp_path / "training.sqlite"
    install_fake_market(monkeypatch, [10, 9, 8, 7, 6])
    collector.collect_once(db, max_universe=220, sleep_s=0, max_rank=20, entry_rank=5, post_exit_bars=12)

    # C1 disappears from the liquidity universe entirely, but exit is now delayed by 1HR post-exit.
    universe = [
        {"inst_id": f"C{i}-USDT", "base_ccy": f"C{i}", "quote_vol_24h": 10_000 - i, "ticker_last": 1.0}
        for i in range(2, 6)
    ]
    candles = {
        item["inst_id"]: make_candles(base=100 + i, change_pct=9 - i)
        for i, item in enumerate(universe, 2)
    }
    # Still allow candle fetches for C1 so post-exit collection can proceed.
    candles["C1-USDT"] = make_candles(base=101, change_pct=9)
    monkeypatch.setattr(collector, "fetch_universe", lambda max_universe: universe)
    monkeypatch.setattr(collector, "fetch_5m", lambda inst_id, limit=20: candles[inst_id])
    result = collector.collect_once(db, max_universe=220, sleep_s=0, max_rank=20, entry_rank=5, post_exit_bars=12)

    assert "C1-USDT" in result["closed"]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT is_active, exit_reason, post_exit_bars_remaining FROM top10_1h_training_sessions WHERE inst_id='C1-USDT'").fetchone()
    assert row["exit_reason"] == "left_liquidity_universe_220"
    assert row["is_active"] == 1
    assert row["post_exit_bars_remaining"] == 11
