"""
Paper trading: records every live BUY/SELL signal and Kronos up/down call, then
grades each one after the next hour, so the tool is judged on real sessions
before any money goes in.

A call made on the 15m bar ending at T is entered at the open of the next bar
and closed at the close of the 4th bar (one hour, the horizon the agents and
Kronos are built for). Cost: 1 tick of slippage on each side. Calls that would
run past the session close are not taken (no overnight holds).

Runs from .github/workflows/paper.yml during TSE hours. The ledger lives on the
paper-trades branch; the site reads its summary live.

    python paper_trader.py ledger.json        # reads and updates the ledger in place
"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import kronos_feed
import kronos_intraday as ki
from data_provider import complete_bars, get_provider
from market_rules import JST, tick_size
from universe import STOCKS_UNIVERSE

HORIZON = ki.HORIZON_BARS
META = {s["symbol"]: s for s in STOCKS_UNIVERSE}
SOURCES = {"engine": "エンジン (BUY/SELL)", "kronos": "Kronos"}


def same_session_room(signal_bar):
    """True when the HORIZON bars after signal_bar all fall in the same session."""
    fut = ki.future_bar_times(signal_bar.replace(tzinfo=None), HORIZON)
    return fut[-1].date() == signal_bar.date()


def new_calls(engine_rows, kronos_feed_data, now):
    calls = []
    for r in engine_rows:
        if r.get("action") not in ("BUY", "SELL"):
            continue
        calls.append({"source": "engine", "symbol": r["symbol"], "signal": r["signal"],
                      "side": 1 if r["action"] == "BUY" else -1, "signal_bar": r["last_bar"]})
    for sym, fc in (kronos_feed_data.get("forecasts") or {}).items():
        if fc.get("direction") not in ("up", "down") or not fc.get("last_bar"):
            continue
        calls.append({"source": "kronos", "symbol": sym, "signal": f"KRONOS {fc['direction']} {fc['expected_move_pct']}%",
                      "side": 1 if fc["direction"] == "up" else -1, "signal_bar": fc["last_bar"]})
    out = []
    for c in calls:
        bar = datetime.fromisoformat(c["signal_bar"]).astimezone(JST)
        if c["symbol"] not in META or not same_session_room(bar):
            continue
        c.update({"id": f"{c['source']}|{c['symbol']}|{c['signal_bar']}", "recorded_at": now.isoformat(timespec="seconds"),
                  "status": "open", "cap": META[c["symbol"]]["cap"]})
        out.append(c)
    return out


def grade(trade, bars):
    """Fill entry/exit from 15m bars once the hour is over. Returns True when graded."""
    if bars is None or len(bars) == 0:
        return False
    idx = pd.DatetimeIndex(bars.index)
    idx = idx.tz_convert("Asia/Tokyo") if idx.tz is not None else idx.tz_localize("Asia/Tokyo")
    sig = pd.Timestamp(trade["signal_bar"]).tz_convert("Asia/Tokyo")
    after = np.flatnonzero(idx > sig)
    if len(after) < HORIZON:
        return False
    first, last = after[0], after[HORIZON - 1]
    if idx[last].date() != sig.date():
        trade.update({"status": "skipped", "reason": "crosses the session close"})
        return True
    entry, exit_ = float(bars["Open"].iloc[first]), float(bars["Close"].iloc[last])
    tick = tick_size(entry, META[trade["symbol"]]["topix500"])
    gross = trade["side"] * (exit_ - entry) / entry * 1e4
    cost = 2 * tick / entry * 1e4
    trade.update({"status": "done", "entry_bar": idx[first].isoformat(), "exit_bar": idx[last].isoformat(),
                  "entry": entry, "exit": exit_, "gross_bps": round(gross, 2), "cost_bps": round(cost, 2),
                  "net_bps": round(gross - cost, 2)})
    return True


def summarize(trades):
    done = [t for t in trades if t["status"] == "done"]
    out = {}
    for key, label in [("all", "全体")] + list(SOURCES.items()):
        g = [t for t in done if key == "all" or t["source"] == key]
        if not g:
            out[key] = {"label": label, "trades": 0}
            continue
        df = pd.DataFrame(g)
        df["day"] = df["entry_bar"].str[:10]
        daily = df.groupby("day").net_bps.mean()
        t = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 and daily.std(ddof=1) > 0 else None
        out[key] = {
            "label": label, "trades": int(len(df)), "days": int(df["day"].nunique()),
            "hit_rate": round(float((df.gross_bps > 0).mean()), 3),
            "gross_bps": round(float(df.gross_bps.mean()), 2),
            "net_bps": round(float(df.net_bps.mean()), 2),
            "day_t": round(float(t), 2) if t is not None else None,
        }
    return out


def run(ledger, engine_rows, kronos_data, frames, now):
    trades = ledger.get("trades", [])
    known = {t["id"] for t in trades}
    for c in new_calls(engine_rows, kronos_data, now):
        if c["id"] not in known:
            trades.append(c)
            known.add(c["id"])
    graded = sum(grade(t, frames.get(t["symbol"])) for t in trades if t["status"] == "open")
    ledger.update({
        "started_at": ledger.get("started_at") or now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "rules": "次の足の始値で入り、4本後 (1時間後) の終値で手仕舞い。片道1ティックのコスト控除。引けをまたぐ取引は除外。",
        "trades": trades,
        "summary": summarize(trades),
        "open": sum(t["status"] == "open" for t in trades),
    })
    return graded


def main(argv):
    path = argv[0] if argv else "ledger.json"
    ledger = {}
    if os.path.exists(path) and os.path.getsize(path):
        with open(path) as f:
            ledger = json.load(f)
    now = datetime.now(JST)
    import app  # the live engine, exactly as the site computes it
    engine_rows = app._analyze_screener()
    provider = get_provider()
    frames = {s: complete_bars(df, "15m", provider.delay_minutes)
              for s, df in provider.history_batch(list(META), interval="15m", period="5d").items()}
    graded = run(ledger, engine_rows, kronos_feed.fetch(), frames, now)
    with open(path, "w") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    # Small file for the site (the ledger grows every session)
    with open(os.path.join(os.path.dirname(os.path.abspath(path)), "summary.json"), "w") as f:
        json.dump({k: ledger[k] for k in ("started_at", "updated_at", "rules", "summary", "open")}, f, ensure_ascii=False)
    print(f"graded {graded}, open {ledger['open']}, total {len(ledger['trades'])}")
    print(json.dumps(ledger["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
