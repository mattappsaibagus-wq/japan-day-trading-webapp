#!/usr/bin/env python3
"""
Heartbeat: keeps the site's jobs on time without relying on GitHub's cron.

GitHub's scheduled triggers are throttled: on 2026-10-20/21 the 15-minute
snapshot cron never fired during market hours and the "twice an hour" doctor
ran every 2-3 hours. So this job keeps its own clock instead. It runs inside one
GitHub Actions job (.github/workflows/heartbeat.yml), checks the JST time every
30 seconds and starts the other workflows with workflow_dispatch:

    snapshot.yml  every 15 min, 09:07-16:07 JST  (bar close + Yahoo's 20 min delay)
    kronos.yml    every 30 min, 09:09-15:39 JST, and 15:59
    paper.yml     every 30 min, 09:20-15:50 JST, and 16:15

on TSE trading days only. Before the job's 6-hour limit it starts a fresh copy of
itself and exits, so the chain keeps running. A dispatch made with the job's own
token does start a new run (GitHub's exception for workflow_dispatch). If the
chain ever breaks, the doctor and the backup crons start it again.

Set HEARTBEAT_DRY_RUN=1 to print instead of dispatching.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from market_rules import JST, is_trading_day  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "mattappsaibagus-wq/japan-day-trading-webapp")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REF = os.environ.get("HEARTBEAT_REF", "master")
DRY_RUN = os.environ.get("HEARTBEAT_DRY_RUN", "").strip() in ("1", "true", "yes")
RUN_FOR = timedelta(minutes=float(os.environ.get("HEARTBEAT_RUN_MINUTES", "340")))  # job limit is 360
TICK_S = 30


def _slots(start, end, every):
    """(h, m) from start to end inclusive, every `every` minutes."""
    out, t = [], start[0] * 60 + start[1]
    while t <= end[0] * 60 + end[1]:
        out.append((t // 60, t % 60))
        t += every
    return out


SCHEDULE = {
    "snapshot.yml": _slots((9, 7), (16, 7), 15),
    "kronos.yml": _slots((9, 9), (15, 39), 30) + [(15, 59)],
    "paper.yml": _slots((9, 20), (15, 50), 30) + [(16, 15)],
}
SELF = "heartbeat.yml"


def due(now, last):
    """Workflows whose slot has arrived since they were last started.
    `last` maps workflow -> datetime of its last dispatch (or None).
    A slot counts once; a slot more than 10 minutes old is skipped, so a late
    start does not fire a burst of catch-up runs."""
    if not is_trading_day(now.date()):
        return []
    out = []
    for wf, slots in SCHEDULE.items():
        for h, m in slots:
            slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot <= now < slot + timedelta(minutes=10) and (last.get(wf) is None or last[wf] < slot):
                out.append(wf)
                break
    return out


def dispatch(wf):
    if DRY_RUN or not TOKEN:
        print(f"[heartbeat] would start {wf}", flush=True)
        return True
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/dispatches", method="POST",
        data=json.dumps({"ref": REF}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "User-Agent": "kabutrader-heartbeat"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
        print(f"[heartbeat] {datetime.now(JST):%H:%M:%S} started {wf}", flush=True)
        return True
    except Exception as e:
        print(f"[heartbeat] could not start {wf}: {e}", flush=True)
        return False


def main():
    started = datetime.now(JST)
    last = {}
    print(f"[heartbeat] up at {started:%Y-%m-%d %H:%M} JST, handing over after {RUN_FOR}", flush=True)
    while datetime.now(JST) - started < RUN_FOR:
        now = datetime.now(JST)
        for wf in due(now, last):
            if dispatch(wf):
                last[wf] = now
        time.sleep(TICK_S)
    # Hand over to a fresh run before the job limit; the concurrency group makes it wait for this one.
    if not dispatch(SELF):
        sys.exit(1)


if __name__ == "__main__":
    main()
