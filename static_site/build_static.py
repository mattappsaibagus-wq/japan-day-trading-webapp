"""
Builds a static snapshot of the terminal for free static hosting (Netlify, etc.).

Runs every API endpoint once through the Flask test client and writes the JSON
next to the rendered page, so the site needs no server or functions.
.github/workflows/snapshot.yml runs this every 15 minutes during TSE hours and
publishes dist/snapshot/ to the snapshot-data branch, which static_site/shim.js
reads live. The copy bundled into a Netlify upload is only a fallback, so the
site itself needs redeploying only when the page code changes.

    python static_site/build_static.py [out_dir]
    python static_site/build_static.py --kronos-only [out_dir]   # refresh Kronos forecasts only
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app  # noqa: E402
from universe import STOCKS_UNIVERSE  # noqa: E402
from market_rules import JST, is_trading_day, jpholiday  # noqa: E402
import kronos_feed  # noqa: E402

INTERVALS = ("5m", "15m", "1d")


def get_json(client, url):
    r = client.get(url)
    return r.status_code, r.get_json()


def upcoming_holidays(start, days=21):
    """Weekdays in the coming weeks when the TSE is shut, {"YYYY-MM-DD": name}.
    The page uses these to tell the session state without a server."""
    out = {}
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() < 5 and not is_trading_day(d):
            out[d.isoformat()] = (jpholiday.is_holiday_name(d) if jpholiday else None) or "年末年始"
    return out


def write_kronos(api_dir):
    feed = kronos_feed.fetch()
    with open(os.path.join(api_dir, "kronos.json"), "w") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))
    print(f"kronos: {len(feed['forecasts'])} forecasts, generated {feed['generated_at']}")


def main(out):
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(out, "static"))
    shutil.copy(os.path.join(ROOT, "static_site", "shim.js"), os.path.join(out, "static", "js", "shim.js"))
    api = os.path.join(out, "snapshot")
    os.makedirs(os.path.join(api, "stock"))

    client = app.test_client()
    built_at = datetime.now(JST).isoformat(timespec="minutes")

    _, macro = get_json(client, "/api/macro")
    _, screener = get_json(client, "/api/screener")
    _, session = get_json(client, "/api/session")
    stocks = 0
    for meta in STOCKS_UNIVERSE:
        for iv in INTERVALS:
            code, body = get_json(client, f"/api/stock/{meta['symbol']}?interval={iv}")
            if code == 200 and body.get("success"):
                with open(os.path.join(api, "stock", f"{meta['symbol']}_{iv}.json"), "w") as f:
                    json.dump(body, f, ensure_ascii=False, separators=(",", ":"))
                stocks += 1
            else:
                print(f"skip {meta['symbol']} {iv}: {code} {body and body.get('error')}")

    last_bars = [s["last_bar"] for s in screener["stocks"]]
    snapshot = {"built_at": built_at, "last_bar": max(last_bars) if last_bars else None,
                "macro": macro, "screener": screener, "session": session,
                "holidays": upcoming_holidays(datetime.now(JST).date())}
    with open(os.path.join(api, "snapshot.json"), "w") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))

    write_kronos(api)

    html = client.get("/").get_data(as_text=True)
    html = html.replace('<script src="/static/js/app.js"></script>',
                        '<script src="/static/js/shim.js"></script>\n  <script src="/static/js/app.js"></script>')
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(html)

    print(f"built {out}: {len(screener['stocks'])} screener rows, {stocks} stock files, as of {built_at}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--kronos-only"]:
        # Refresh only the Kronos forecasts in an existing build, keeping its market snapshot
        write_kronos(os.path.join(args[1] if len(args) > 1 else os.path.join(ROOT, "dist"), "snapshot"))
    else:
        main(args[0] if args else os.path.join(ROOT, "dist"))
