import scan_pretop30_takeoff_strategies as scan


def _rank(inst_id, rank, change=1.2, last=100.0, vol=1.0):
    return {
        "inst_id": inst_id,
        "rank_1h": rank,
        "change_1h_pct": change,
        "last": last,
        "vol_ratio_5m": vol,
    }


def _snap(ts, rows):
    return {"ts": ts, "ranks": {r["inst_id"]: r for r in rows}}


def test_candidate_events_use_only_new_pretop30_entries_and_skip_previous_top10():
    snaps = [
        _snap("2026-06-01T00:00+08:00", [_rank("AAA", 9), _rank("BBB", 12), _rank("CCC", 31)]),
        _snap("2026-06-01T01:00+08:00", [_rank("AAA", 12), _rank("BBB", 13), _rank("CCC", 20), _rank("DDD", 15)]),
        _snap("2026-06-01T02:00+08:00", [_rank("BBB", 14), _rank("DDD", 16), _rank("EEE", 11)]),
    ]

    events = scan.candidate_events(snaps)

    # BBB is captured once when it newly enters rank 11-30. AAA is skipped
    # because it was Top10 on the previous snapshot. DDD is not duplicated while
    # it remains pre-Top10. CCC only becomes an event when it moves into rank 20.
    assert [(e["inst_id"], e["idx"], e["rank"]) for e in events] == [
        ("BBB", 0, 12),
        ("CCC", 1, 20),
        ("DDD", 1, 15),
        ("EEE", 2, 11),
    ]


def test_oracle_filter_requires_future_top10_but_live_filter_does_not():
    snaps = [
        _snap("2026-06-01T00:00+08:00", [_rank("AAA", 12, last=100.0)]),
        _snap("2026-06-01T01:00+08:00", [_rank("AAA", 11, last=101.0)]),
        _snap("2026-06-01T02:00+08:00", [_rank("AAA", 9, last=103.0)]),
    ]
    event = scan.candidate_events(snaps)[0]
    live = scan.Params(11, 20, 1, 2, 0, 2, 1.0, False, 0)
    oracle = scan.Params(11, 20, 1, 2, 0, 2, 1.0, True, 1)
    oracle_ok = scan.Params(11, 20, 1, 2, 0, 2, 1.0, True, 2)

    assert scan.simulate(snaps, event, live)["entered_top10_at"] == 2
    assert scan.simulate(snaps, event, oracle) is None
    assert scan.simulate(snaps, event, oracle_ok)["entered_top10_at"] == 2


def test_scan_splits_implementable_live_summaries_before_oracle_diagnostics():
    snaps = [
        _snap("2026-06-01T00:00+08:00", [_rank("AAA", 12, last=100.0)]),
        _snap("2026-06-01T01:00+08:00", [_rank("AAA", 9, last=102.0)]),
        _snap("2026-06-01T02:00+08:00", [_rank("AAA", 8, last=104.0)]),
    ]
    grid = [
        scan.Params(11, 20, 1, 2, 0, 2, 1.0, True, 2),
        scan.Params(11, 20, 1, 2, 0, 2, 1.0, False, 0),
    ]

    out = scan.scan_snapshots(snaps, min_trades=1, grid=grid, db_label="unit")

    assert out["db"] == "unit"
    assert "future Top10" in out["note"]
    assert len(out["live_summaries"]) == 1
    assert len(out["oracle_summaries"]) == 1
    assert out["summaries"][0]["params"]["require_enter_top10"] is False
    assert out["summaries"][1]["params"]["require_enter_top10"] is True
