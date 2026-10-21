from datetime import datetime

import heartbeat
from market_rules import JST


def t(h, m, s=0, day=21):
    return datetime(2026, 10, day, h, m, s, tzinfo=JST)


def test_snapshot_every_15_min_in_market_hours():
    assert "snapshot.yml" in heartbeat.due(t(9, 7, 5), {})
    assert "snapshot.yml" in heartbeat.due(t(10, 22, 30), {})
    assert "snapshot.yml" in heartbeat.due(t(16, 7), {})
    assert "snapshot.yml" not in heartbeat.due(t(10, 18), {})  # 11 min after the 10:07 slot
    assert heartbeat.due(t(8, 50), {}) == []
    assert heartbeat.due(t(17, 7), {}) == []


def test_each_slot_fires_once():
    last = {"snapshot.yml": t(10, 22, 1)}
    assert "snapshot.yml" not in heartbeat.due(t(10, 22, 31), last)
    assert "snapshot.yml" in heartbeat.due(t(10, 37), last)


def test_old_slots_are_not_replayed():
    # started at 10:33: the 10:22 slot is 11 minutes old, so nothing fires until 10:37
    assert "snapshot.yml" not in heartbeat.due(t(10, 33), {})


def test_kronos_and_paper_slots():
    assert "kronos.yml" in heartbeat.due(t(9, 39), {})
    assert "kronos.yml" in heartbeat.due(t(15, 59), {})
    assert "paper.yml" in heartbeat.due(t(9, 50), {})
    assert "paper.yml" in heartbeat.due(t(16, 15), {})


def test_quiet_on_weekends_and_holidays():
    assert heartbeat.due(t(10, 7, day=24), {}) == []          # Saturday
    assert heartbeat.due(datetime(2026, 11, 3, 10, 7, tzinfo=JST), {}) == []  # 文化の日
