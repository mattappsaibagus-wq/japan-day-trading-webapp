#!/usr/bin/env python3
"""
Site doctor: checks minnanokabu.netlify.app and the Kronos job on a schedule, so
the site's health is known at any time, not only while someone has it open.

Runs from .github/workflows/doctor.yml every hour and after every Kronos run.

  1. Diagnose - the live site answers, how old its market snapshot is, whether
                the snapshot is complete, how old the Kronos forecasts are and
                whether the last Kronos run succeeded.
  2. Fix      - only safe, scripted fixes for things GitHub can redo:
                  * start the Kronos job when its forecasts are stale
                  * re-run a failed Kronos run once
                  * start the market snapshot job when its data is stale
                All are rate-limited through state kept in health.json. GitHub's
                cron often skips or delays runs, so this is what keeps the site
                current when a scheduled run does not happen.
  3. Report   - writes health.json, which the site reads live (it is not part
                of the snapshot) to show Health OK / STALE / BROKEN.

Each check is ok, stale or broken; the overall status is the worst of them.
Set DOCTOR_DRY_RUN=1 to check without fixing.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from market_rules import JST, is_trading_day  # noqa: E402

SITE = os.environ.get("DOCTOR_SITE", "https://minnanokabu.netlify.app")
REPO = os.environ.get("GITHUB_REPOSITORY", "mattappsaibagus-wq/japan-day-trading-webapp")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
KRONOS_WORKFLOW = "kronos.yml"
KRONOS_FEED = f"https://raw.githubusercontent.com/{REPO}/kronos-data/kronos.json"
SNAPSHOT_WORKFLOW = "snapshot.yml"
# The site reads market data live from this branch (static_site/shim.js)
SNAPSHOT_FEED = f"https://raw.githubusercontent.com/{REPO}/snapshot-data/snapshot.json"
PREV_PATH = os.environ.get("DOCTOR_PREV_HEALTH", "")
OUT_PATH = os.environ.get("DOCTOR_OUT", os.path.join(ROOT, "health.json"))
DRY_RUN = os.environ.get("DOCTOR_DRY_RUN", "").strip() in ("1", "true", "yes")

FEED_DELAY = timedelta(minutes=20)      # Yahoo TSE delay
SNAPSHOT_SLACK = timedelta(minutes=45)  # snapshot may trail the latest bar this much
KRONOS_SLACK = timedelta(minutes=90)    # Kronos runs every 30 min; GitHub cron starts late
KRONOS_MIN_COVERAGE = 0.75              # share of screener stocks with a forecast
DISPATCH_COOLDOWN = timedelta(minutes=60)
SNAPSHOT_DISPATCH_COOLDOWN = timedelta(minutes=25)  # the snapshot job takes a few minutes
RANK = {"ok": 0, "stale": 1, "broken": 2}


# ---------------------------------------------------------------- helpers

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "minnanokabu-doctor", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url):
    return json.loads(http_get(url)[1])


def gh(method, path, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "minnanokabu-doctor"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def parse_time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST)


def fmt(dt):
    return dt.astimezone(JST).strftime("%m/%d %H:%M JST")


def age(now, dt):
    mins = int((now - dt).total_seconds() // 60)
    return f"{mins}分前" if mins < 120 else f"{mins // 60}時間前" if mins < 48 * 60 else f"{mins // 1440}日前"


SLOTS = [(h, m) for h in range(9, 16) for m in (0, 15, 30, 45)
         if (9, 0) <= (h, m) <= (11, 15) or (12, 30) <= (h, m) <= (15, 15)]


def expected_last_bar(now):
    """Start of the newest 15m bar Yahoo should have finished delivering by `now`."""
    d = now.date()
    for _ in range(15):
        if is_trading_day(d):
            for h, m in reversed(SLOTS):
                start = datetime(d.year, d.month, d.day, h, m, tzinfo=JST)
                if start + timedelta(minutes=15) + FEED_DELAY <= now:
                    return start
        d -= timedelta(days=1)
    return None


# ---------------------------------------------------------------- checks

def check_site():
    try:
        status, body = http_get(SITE + "/")
        if status == 200 and b"KABUTRADER" in body:
            return {"name": "サイト稼働", "status": "ok", "detail": f"{SITE} 応答 OK"}
        return {"name": "サイト稼働", "status": "broken", "detail": f"HTTP {status} だがページ内容が想定外"}
    except Exception as e:
        return {"name": "サイト稼働", "status": "broken", "detail": f"応答なし ({type(e).__name__}: {e})"}


def check_snapshot(now):
    """Returns (checks, screener_count, stale)."""
    try:
        snap = get_json(SNAPSHOT_FEED)
    except Exception as e:
        return [{"name": "市場データ", "status": "broken", "detail": f"snapshot.json を読めません ({e})"}], 0, True
    checks = []
    rows = len((snap.get("screener") or {}).get("stocks") or [])
    checks.append({"name": "スクリーナー", "status": "ok" if rows else "broken",
                   "detail": f"{rows} 銘柄" if rows else "銘柄データが空です"})
    last = snap.get("last_bar")
    expected = expected_last_bar(now)
    behind = True
    if not last:
        checks.append({"name": "市場データ", "status": "broken", "detail": "最終足の時刻がありません"})
    else:
        last_dt = parse_time(last)
        behind = bool(expected and last_dt < expected - SNAPSHOT_SLACK)
        detail = f"最終足 {fmt(last_dt)} ({age(now, last_dt)})"
        if behind:
            detail += f" · 最新は {fmt(expected)} の足。更新ジョブ ({SNAPSHOT_WORKFLOW}) が遅れています"
        checks.append({"name": "市場データ", "status": "stale" if behind else "ok", "detail": detail})
    try:
        get_json(SITE + "/snapshot/snapshot.json")
    except Exception:
        checks.append({"name": "スナップショット内容", "status": "broken", "detail": "サイトに予備データがありません"})
    return checks, rows, behind


def check_kronos_feed(now, screener_rows):
    try:
        feed = get_json(KRONOS_FEED)
    except Exception as e:
        return {"name": "Kronos 予測", "status": "broken", "detail": f"予測ファイルを読めません ({e})"}, True
    gen = parse_time(feed["generated_at"])
    n = len(feed.get("forecasts") or {})
    expected = expected_last_bar(now)
    stale = bool(expected) and gen < expected + FEED_DELAY + timedelta(minutes=15) - KRONOS_SLACK
    low = screener_rows and n < KRONOS_MIN_COVERAGE * screener_rows
    status = "stale" if stale else "broken" if low or not n else "ok"
    detail = f"{fmt(gen)} 更新 ({age(now, gen)}) · {n} 銘柄"
    if stale:
        detail += " · 予測が古い"
    if low:
        detail += f" · 対象 {screener_rows} 銘柄に対して少なすぎます"
    return {"name": "Kronos 予測", "status": status, "detail": detail}, stale


def latest_kronos_runs():
    if not TOKEN:
        return None
    try:
        return gh("GET", f"/repos/{REPO}/actions/workflows/{KRONOS_WORKFLOW}/runs?per_page=5"
                         f"&exclude_pull_requests=true").get("workflow_runs", [])
    except Exception as e:
        print(f"[doctor] could not list Kronos runs: {e}", flush=True)
        return None


def check_kronos_job(runs):
    if runs is None:
        return {"name": "Kronos ジョブ", "status": "ok", "detail": "実行履歴を確認できません (トークンなし)"}
    done = [r for r in runs if r.get("status") == "completed"]
    if not done:
        return {"name": "Kronos ジョブ", "status": "ok", "detail": "まだ実行履歴がありません"}
    last = done[0]
    when = fmt(parse_time(last["updated_at"]))
    if last.get("conclusion") == "success":
        return {"name": "Kronos ジョブ", "status": "ok", "detail": f"最終実行 {when} 成功"}
    return {"name": "Kronos ジョブ", "status": "broken",
            "detail": f"最終実行 {when} {last.get('conclusion')} · {last.get('html_url')}"}


# ---------------------------------------------------------------- fixes

def fix_kronos(now, runs, feed_stale, prev_state, state):
    """Re-run a failed run once, or start a run when forecasts are stale. Returns fix records."""
    if runs is None or not TOKEN:
        return []
    active = [r for r in runs if r.get("status") in ("queued", "in_progress", "waiting", "requested")]
    done = [r for r in runs if r.get("status") == "completed"]
    last_dispatch = prev_state.get("kronos_dispatch_at")
    if last_dispatch:
        state["kronos_dispatch_at"] = last_dispatch
    cooling = last_dispatch and now - parse_time(last_dispatch) < DISPATCH_COOLDOWN
    fixes = []
    if active:
        return fixes
    if done and done[0].get("conclusion") == "failure" and done[0].get("run_attempt", 1) == 1:
        action = f"失敗した Kronos 実行を再実行 ({done[0]['html_url']})"
        if DRY_RUN:
            return [{"action": action, "done": False, "result": "dry run"}]
        try:
            gh("POST", f"/repos/{REPO}/actions/runs/{done[0]['id']}/rerun-failed-jobs")
            return [{"action": action, "done": True, "result": "再実行を開始"}]
        except Exception as e:
            return [{"action": action, "done": False, "result": str(e)}]
    if feed_stale and is_trading_day(now.date()) and not cooling:
        action = "古い Kronos 予測のためジョブを開始"
        if DRY_RUN:
            return [{"action": action, "done": False, "result": "dry run"}]
        try:
            gh("POST", f"/repos/{REPO}/actions/workflows/{KRONOS_WORKFLOW}/dispatches", {"ref": "master"})
            state["kronos_dispatch_at"] = now.isoformat(timespec="seconds")
            fixes.append({"action": action, "done": True, "result": "Kronos ジョブを開始"})
        except Exception as e:
            fixes.append({"action": action, "done": False, "result": str(e)})
    return fixes


def fix_snapshot(now, stale, prev_state, state):
    """Start the snapshot job when the live market data is behind (trading days only)."""
    last = prev_state.get("snapshot_dispatch_at")
    if last:
        state["snapshot_dispatch_at"] = last
    if not stale or not TOKEN or not is_trading_day(now.date()):
        return []
    if last and now - parse_time(last) < SNAPSHOT_DISPATCH_COOLDOWN:
        return []
    try:
        runs = gh("GET", f"/repos/{REPO}/actions/workflows/{SNAPSHOT_WORKFLOW}/runs?per_page=3"
                         f"&exclude_pull_requests=true").get("workflow_runs", [])
    except Exception as e:
        print(f"[doctor] could not list snapshot runs: {e}", flush=True)
        runs = []
    if any(r.get("status") in ("queued", "in_progress", "waiting", "requested") for r in runs):
        return []
    action = "古い市場データのため更新ジョブを開始"
    if DRY_RUN:
        return [{"action": action, "done": False, "result": "dry run"}]
    try:
        gh("POST", f"/repos/{REPO}/actions/workflows/{SNAPSHOT_WORKFLOW}/dispatches", {"ref": "master"})
        state["snapshot_dispatch_at"] = now.isoformat(timespec="seconds")
        return [{"action": action, "done": True, "result": "更新ジョブを開始"}]
    except Exception as e:
        return [{"action": action, "done": False, "result": str(e)}]


# ---------------------------------------------------------------- main

def diagnose(now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    prev = {}
    if PREV_PATH and os.path.exists(PREV_PATH):
        try:
            with open(PREV_PATH) as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    checks = [check_site()]
    snap_checks, rows, snap_stale = check_snapshot(now)
    checks += snap_checks
    kronos_check, feed_stale = check_kronos_feed(now, rows)
    checks.append(kronos_check)
    runs = latest_kronos_runs()
    checks.append(check_kronos_job(runs))

    state = {}
    prev_state = prev.get("state") or {}
    fixes = fix_kronos(now, runs, feed_stale, prev_state, state)
    fixes += fix_snapshot(now, snap_stale, prev_state, state)
    status = max((c["status"] for c in checks), key=RANK.get)
    return {"checked_at": now.isoformat(timespec="seconds"), "status": status, "site": SITE,
            "checks": checks, "fixes": fixes, "state": state}


def main():
    report = diagnose()
    with open(OUT_PATH, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"status: {report['status']}")
    for c in report["checks"]:
        print(f"  [{c['status']:6}] {c['name']}: {c['detail']}")
    for x in report["fixes"]:
        print(f"  fix: {x['action']} -> {x['result']}")


if __name__ == "__main__":
    main()
