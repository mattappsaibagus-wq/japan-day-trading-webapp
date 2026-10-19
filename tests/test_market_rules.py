from datetime import date, datetime

import pytest

from market_rules import JST, is_trading_day, position_size, price_limits, round_to_tick, session_status, tick_size


@pytest.mark.parametrize("price,topix500,expected", [
    (2999, False, 1), (3001, False, 5), (5000, False, 5), (5001, False, 10), (30001, False, 50),
    (999, True, 0.1), (1500, True, 0.5), (3001, True, 1), (12000, True, 5), (50000, True, 10),
])
def test_tick_size(price, topix500, expected):
    assert tick_size(price, topix500) == expected


def test_round_to_tick_directions():
    assert round_to_tick(3002.3, False, "down") == 3000
    assert round_to_tick(3002.3, False, "up") == 3005
    assert round_to_tick(1234.37, True) == 1234.5
    assert round_to_tick(1234.37, True, "down") == 1234.0


def test_price_limits():
    assert price_limits(2999)["width"] == 500
    assert price_limits(3000)["width"] == 700
    lim = price_limits(1000)
    assert (lim["limit_up"], lim["limit_down"]) == (1300, 700)


def test_position_size_risk_limited():
    # ¥3M account, 1% risk = ¥30,000; ¥20/share risk -> 1,500 shares -> 15 lots
    r = position_size(3_000_000, 1.0, 1000, 980)
    assert r["shares"] == 1500 and r["lots"] == 15 and r["limited_by"] == "risk"
    assert r["risk_jpy"] <= r["risk_budget"]


def test_position_size_capital_limited():
    r = position_size(1_000_000, 2.0, 5000, 4990)
    assert r["shares"] == 200 and r["limited_by"] == "capital"


def test_position_size_unit_too_big():
    r = position_size(500_000, 0.5, 10000, 9800)  # 1 unit risks ¥20,000 > ¥2,500 budget
    assert r["shares"] == 0 and "exceeds" in r["limited_by"]


def test_calendar():
    assert not is_trading_day(date(2026, 1, 2))      # JPX year-end holiday
    assert not is_trading_day(date(2026, 10, 17))    # Saturday
    assert is_trading_day(date(2026, 10, 19))


@pytest.mark.parametrize("hm,state", [((8, 30), "pre_open"), ((10, 0), "morning"), ((12, 0), "lunch"),
                                      ((15, 27), "closing_auction"), ((15, 31), "closed")])
def test_session_status(hm, state):
    assert session_status(datetime(2026, 10, 19, *hm, tzinfo=JST))["state"] == state
