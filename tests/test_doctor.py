import json
from datetime import datetime

from doctor import doctor
from market_rules import JST


def test_expected_last_bar_respects_delay_lunch_and_weekend():
    assert doctor.expected_last_bar(datetime(2026, 10, 20, 10, 40, tzinfo=JST)) == datetime(2026, 10, 20, 10, 0, tzinfo=JST)
    assert doctor.expected_last_bar(datetime(2026, 10, 20, 12, 45, tzinfo=JST)) == datetime(2026, 10, 20, 11, 15, tzinfo=JST)
    # Monday before the open -> Friday's last bar
    assert doctor.expected_last_bar(datetime(2026, 10, 19, 8, 0, tzinfo=JST)) == datetime(2026, 10, 16, 15, 15, tzinfo=JST)


def _fake_site(monkeypatch, last_bar, kronos_at, n=33):
    snap = {"last_bar": last_bar, "screener": {"stocks": [{}] * 33}}
    feed = {"generated_at": kronos_at, "forecasts": {str(i): {} for i in range(n)}}

    def get_json(url):
        if url.endswith("snapshot.json"):
            return snap
        if url.endswith("kronos.json") and "raw.githubusercontent" in url:
            return feed
        return {"forecasts": {}}

    monkeypatch.setattr(doctor, "http_get", lambda url, timeout=20: (200, b"<span>KABUTRADER</span>"))
    monkeypatch.setattr(doctor, "get_json", get_json)
    monkeypatch.setattr(doctor, "TOKEN", "")


def test_fresh_site_is_ok(monkeypatch):
    _fake_site(monkeypatch, "2026-10-20T10:00:00+09:00", "2026-10-20T10:38:00+09:00")
    report = doctor.diagnose(datetime(2026, 10, 20, 10, 50, tzinfo=JST))
    assert report["status"] == "ok", json.dumps(report, ensure_ascii=False)


def test_old_snapshot_is_stale_and_says_why(monkeypatch):
    _fake_site(monkeypatch, "2026-10-19T15:15:00+09:00", "2026-10-20T10:38:00+09:00")
    report = doctor.diagnose(datetime(2026, 10, 20, 10, 50, tzinfo=JST))
    assert report["status"] == "stale"
    market = next(c for c in report["checks"] if c["name"] == "市場データ")
    assert "snapshot.yml" in market["detail"]


def test_stale_snapshot_starts_the_snapshot_job(monkeypatch):
    _fake_site(monkeypatch, "2026-10-19T15:15:00+09:00", "2026-10-20T10:38:00+09:00")
    calls = []

    def gh(method, path, body=None):
        calls.append((method, path))
        return {"workflow_runs": []}

    monkeypatch.setattr(doctor, "TOKEN", "t")
    monkeypatch.setattr(doctor, "gh", gh)
    monkeypatch.setattr(doctor, "DRY_RUN", False)
    report = doctor.diagnose(datetime(2026, 10, 20, 10, 50, tzinfo=JST))
    assert ("POST", f"/repos/{doctor.REPO}/actions/workflows/snapshot.yml/dispatches") in calls
    assert report["state"]["snapshot_dispatch_at"].startswith("2026-10-20T10:50")
    # inside the cooldown it does not start it again
    calls.clear()
    monkeypatch.setattr(doctor, "PREV_PATH", "")
    assert doctor.fix_snapshot(datetime(2026, 10, 20, 11, 0, tzinfo=JST), True, report["state"], {}) == []


def test_missing_kronos_forecasts_is_broken(monkeypatch):
    _fake_site(monkeypatch, "2026-10-20T10:00:00+09:00", "2026-10-20T10:38:00+09:00", n=3)
    assert doctor.diagnose(datetime(2026, 10, 20, 10, 50, tzinfo=JST))["status"] == "broken"


def test_doctor_restarts_a_stopped_heartbeat(monkeypatch):
    calls = []

    def gh(method, path, body=None):
        calls.append((method, path))
        return {"workflow_runs": [{"status": "completed"}]}

    monkeypatch.setattr(doctor, "TOKEN", "t")
    monkeypatch.setattr(doctor, "gh", gh)
    monkeypatch.setattr(doctor, "DRY_RUN", False)
    assert doctor.fix_heartbeat(datetime(2026, 10, 21, 10, 0, tzinfo=JST))[0]["done"]
    assert ("POST", f"/repos/{doctor.REPO}/actions/workflows/heartbeat.yml/dispatches") in calls


def test_doctor_leaves_a_running_heartbeat(monkeypatch):
    monkeypatch.setattr(doctor, "TOKEN", "t")
    monkeypatch.setattr(doctor, "gh", lambda m, p, b=None: {"workflow_runs": [{"status": "in_progress"}]})
    assert doctor.fix_heartbeat(datetime(2026, 10, 21, 10, 0, tzinfo=JST)) == []
