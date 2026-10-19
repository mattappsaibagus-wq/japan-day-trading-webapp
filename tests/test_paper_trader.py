from datetime import datetime

import pandas as pd

import paper_trader as pt
from market_rules import JST


def _bars(day, prices):
    slots = [(h, m) for h, m in [(10, 0), (10, 15), (10, 30), (10, 45), (11, 0), (11, 15)]]
    idx = pd.DatetimeIndex([f"{day} {h:02d}:{m:02d}" for h, m in slots[:len(prices)]]).tz_localize("Asia/Tokyo")
    return pd.DataFrame({"Open": prices, "Close": prices}, index=idx)


def test_records_buy_sell_and_kronos_calls_but_not_hold_or_late_ones():
    engine = [
        {"symbol": "7203.T", "action": "BUY", "signal": "BUY", "last_bar": "2026-10-20T10:00:00+09:00"},
        {"symbol": "6758.T", "action": "HOLD", "signal": "HOLD", "last_bar": "2026-10-20T10:00:00+09:00"},
        {"symbol": "6501.T", "action": "SELL", "signal": "SELL", "last_bar": "2026-10-20T15:00:00+09:00"},  # no hour left
    ]
    kronos = {"forecasts": {"8306.T": {"direction": "down", "expected_move_pct": -0.4, "last_bar": "2026-10-20T10:00:00+09:00"},
                            "9984.T": {"direction": "flat", "expected_move_pct": 0.1, "last_bar": "2026-10-20T10:00:00+09:00"}}}
    calls = pt.new_calls(engine, kronos, datetime(2026, 10, 20, 10, 40, tzinfo=JST))
    assert sorted((c["source"], c["symbol"], c["side"]) for c in calls) == [("engine", "7203.T", 1), ("kronos", "8306.T", -1)]


def test_grade_enters_next_open_exits_fourth_close_after_costs():
    trade = {"symbol": "7203.T", "side": 1, "signal_bar": "2026-10-20T10:00:00+09:00", "status": "open"}
    bars = _bars("2026-10-20", [3000.0, 3000.0, 3005.0, 3010.0, 3030.0])
    assert pt.grade(trade, bars)
    assert trade["entry"] == 3000.0 and trade["exit"] == 3030.0
    assert trade["gross_bps"] == 100.0
    assert trade["net_bps"] == round(100.0 - 2 * 0.5 / 3000 * 1e4, 2)   # TOPIX500 tick at ¥3,000 is 0.5


def test_ungraded_until_hour_is_over_and_ledger_dedups():
    ledger = {}
    engine = [{"symbol": "7203.T", "action": "BUY", "signal": "BUY", "last_bar": "2026-10-20T10:00:00+09:00"}]
    now = datetime(2026, 10, 20, 10, 40, tzinfo=JST)
    pt.run(ledger, engine, {}, {"7203.T": _bars("2026-10-20", [3000.0, 3000.0])}, now)
    pt.run(ledger, engine, {}, {"7203.T": _bars("2026-10-20", [3000.0, 3000.0, 3001.0])}, now)
    assert len(ledger["trades"]) == 1 and ledger["open"] == 1
    pt.run(ledger, engine, {}, {"7203.T": _bars("2026-10-20", [3000.0, 3000.0, 3005.0, 3010.0, 2990.0])}, now)
    assert ledger["open"] == 0
    assert ledger["summary"]["engine"]["trades"] == 1 and ledger["summary"]["engine"]["hit_rate"] == 0.0
