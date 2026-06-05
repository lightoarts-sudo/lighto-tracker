import replay_pretop30_takeoff_5m as replay
from scan_pretop30_takeoff_strategies import Params


def test_parse_ts_ms_handles_taiwan_timezone():
    assert replay.parse_ts_ms("1970-01-01T08:00:01+08:00") == 1000


def test_guard_blocks_cooldown_and_12h_repeat_limit():
    guards = replay.ReplayGuards(cooldown_minutes=180, max_entries_per_inst_12h=1)
    state = {"cooldown_until": {}, "blacklist_until": {}, "entry_times": {}, "loss_times": {}}
    event = {"inst_id": "AAA-USDT", "ts": "2026-06-01T00:00:00+08:00"}

    ok, reason = replay.passes_guards(event, state, guards)
    assert (ok, reason) == (True, "ok")

    trade = {"inst_id": "AAA-USDT", "entry_ts_ms": replay.parse_ts_ms(event["ts"]), "net_return_pct": -0.5, "exit_reason": "hard_stop"}
    replay.update_guards(trade, state, guards)

    later = {"inst_id": "AAA-USDT", "ts": "2026-06-01T01:00:00+08:00"}
    assert replay.passes_guards(later, state, guards) == (False, "cooldown")

    after_cooldown = {"inst_id": "AAA-USDT", "ts": "2026-06-01T04:00:00+08:00"}
    assert replay.passes_guards(after_cooldown, state, guards) == (False, "max_entries_12h")


def test_blacklist_after_repeated_large_losses():
    guards = replay.ReplayGuards(blacklist_loss_threshold_pct=-1.0, blacklist_loss_count=2, blacklist_hours=24)
    state = {"cooldown_until": {}, "blacklist_until": {}, "entry_times": {}, "loss_times": {}}
    t1 = replay.parse_ts_ms("2026-06-01T00:00:00+08:00")
    t2 = replay.parse_ts_ms("2026-06-01T02:00:00+08:00")

    replay.update_guards({"inst_id": "AAA-USDT", "entry_ts_ms": t1, "net_return_pct": -1.2, "exit_reason": "hard_stop"}, state, guards)
    replay.update_guards({"inst_id": "AAA-USDT", "entry_ts_ms": t2, "net_return_pct": -1.1, "exit_reason": "hard_stop"}, state, guards)

    blocked = {"inst_id": "AAA-USDT", "ts": "2026-06-01T03:00:00+08:00"}
    assert replay.passes_guards(blocked, state, guards) == (False, "blacklisted")


def test_event_matches_only_live_pretop_filters_not_oracle():
    event = {"rank": 12, "chg": 1.5, "vol_ratio": 0.8}
    live = Params(11, 20, 1, 2, 0.5, 6, 1.5, False, 0)
    oracle = Params(11, 20, 1, 2, 0.5, 6, 1.5, True, 3)
    assert replay.event_matches(event, live) is True
    assert replay.event_matches(event, oracle) is False
