"""
TSE market rules for day trading:
  - Tick size table (呼値の単位) — TOPIX500 constituents vs. all other stocks
  - Daily price limits (制限値幅 / ストップ高・ストップ安)
  - Position sizing in 100-share trading units (単元株)
  - Exchange holiday calendar (JPX: national holidays + Dec 31 - Jan 3)

Tables reflect JPX rules as of 2024-2026. JPX revises them occasionally and
can temporarily widen price limits for a stock, so verify against
https://www.jpx.co.jp/ before relying on them for live orders.
"""

import math
from datetime import date, datetime, time as dtime, timedelta, timezone

try:
    import jpholiday
except ImportError:  # calendar degrades to weekends + JPX year-end only
    jpholiday = None

JST = timezone(timedelta(hours=9))
LOT_SIZE = 100  # 単元株数 (all TSE domestic stocks since 2018)

# (upper bound inclusive, tick)
TICK_TABLE_TOPIX500 = [
    (1_000, 0.1), (3_000, 0.5), (10_000, 1), (30_000, 5), (100_000, 10),
    (300_000, 50), (1_000_000, 100), (3_000_000, 500), (10_000_000, 1_000),
    (30_000_000, 5_000), (math.inf, 10_000),
]
TICK_TABLE_STANDARD = [
    (3_000, 1), (5_000, 5), (30_000, 10), (50_000, 50), (300_000, 100),
    (500_000, 500), (3_000_000, 1_000), (5_000_000, 5_000), (30_000_000, 10_000),
    (50_000_000, 50_000), (math.inf, 100_000),
]

# (base price strictly below, limit width) — standard 制限値幅
PRICE_LIMIT_TABLE = [
    (100, 30), (200, 50), (500, 80), (700, 100), (1_000, 150), (1_500, 300),
    (2_000, 400), (3_000, 500), (5_000, 700), (7_000, 1_000), (10_000, 1_500),
    (15_000, 3_000), (20_000, 4_000), (30_000, 5_000), (50_000, 7_000),
    (70_000, 10_000), (100_000, 15_000), (150_000, 30_000), (200_000, 40_000),
    (300_000, 50_000), (500_000, 70_000), (700_000, 100_000), (1_000_000, 150_000),
    (1_500_000, 300_000), (2_000_000, 400_000), (3_000_000, 500_000),
    (5_000_000, 700_000), (7_000_000, 1_000_000), (10_000_000, 1_500_000),
    (15_000_000, 3_000_000), (20_000_000, 4_000_000), (30_000_000, 5_000_000),
    (50_000_000, 7_000_000), (math.inf, 10_000_000),
]


def tick_size(price, topix500=False):
    table = TICK_TABLE_TOPIX500 if topix500 else TICK_TABLE_STANDARD
    for upper, tick in table:
        if price <= upper:
            return tick
    return table[-1][1]


def round_to_tick(price, topix500=False, direction="nearest"):
    """Round a price onto the TSE tick grid. direction: 'up', 'down' or 'nearest'."""
    if price <= 0:
        return 0.0
    tick = tick_size(price, topix500)
    steps = price / tick
    if direction == "up":
        steps = math.ceil(steps - 1e-9)
    elif direction == "down":
        steps = math.floor(steps + 1e-9)
    else:
        steps = round(steps)
    rounded = steps * tick
    # Rounding can cross a band boundary; re-snap with the new band's tick
    new_tick = tick_size(rounded, topix500)
    if new_tick != tick:
        rounded = round(rounded / new_tick) * new_tick
    return round(rounded, 1)


def price_limits(base_price):
    """Daily limit-up / limit-down from the base price (usually prior close)."""
    width = PRICE_LIMIT_TABLE[-1][1]
    for below, w in PRICE_LIMIT_TABLE:
        if base_price < below:
            width = w
            break
    return {
        "base": round(base_price, 1),
        "width": width,
        "limit_up": round(base_price + width, 1),
        "limit_down": round(max(base_price - width, 1), 1),
    }


def position_size(account_jpy, risk_pct, entry, stop, lot=LOT_SIZE, max_capital_pct=100.0):
    """
    Fixed-fractional sizing: shares = (account * risk%) / |entry - stop|,
    floored to whole trading units and capped by available capital.
    """
    risk_per_share = abs(entry - stop)
    if account_jpy <= 0 or risk_pct <= 0 or entry <= 0 or risk_per_share <= 0:
        return {"shares": 0, "lots": 0, "risk_budget": 0, "risk_jpy": 0,
                "capital_jpy": 0, "risk_per_share": round(risk_per_share, 1),
                "limited_by": "invalid input"}

    risk_budget = account_jpy * risk_pct / 100.0
    lots_by_risk = math.floor(risk_budget / (risk_per_share * lot))
    lots_by_capital = math.floor(account_jpy * max_capital_pct / 100.0 / (entry * lot))
    lots = max(0, min(lots_by_risk, lots_by_capital))
    limited_by = "risk" if lots_by_risk <= lots_by_capital else "capital"
    if lots == 0:
        limited_by = "1 unit exceeds risk budget" if lots_by_risk == 0 else "insufficient capital"

    shares = lots * lot
    return {
        "shares": shares,
        "lots": lots,
        "risk_budget": round(risk_budget),
        "risk_jpy": round(shares * risk_per_share),
        "capital_jpy": round(shares * entry),
        "risk_per_share": round(risk_per_share, 1),
        "limited_by": limited_by,
    }


def is_trading_day(d):
    if d.weekday() >= 5:
        return False
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return False
    if jpholiday is not None and jpholiday.is_holiday(d):
        return False
    return True


def session_status(now=None):
    """TSE cash session (since 2024-11-05 the afternoon session closes at 15:30)."""
    now = (now or datetime.now(JST)).astimezone(JST)
    d = now.date()
    if not is_trading_day(d):
        holiday = jpholiday.is_holiday_name(d) if jpholiday is not None else None
        return {"state": "closed", "label": "休場日", "holiday": holiday or ("週末" if d.weekday() >= 5 else "年末年始")}
    t = now.time()
    if t < dtime(8, 0):
        state, label = "closed", "取引時間外"
    elif t < dtime(9, 0):
        state, label = "pre_open", "寄付前 (板寄せ注文受付)"
    elif t < dtime(11, 30):
        state, label = "morning", "前場"
    elif t < dtime(12, 30):
        state, label = "lunch", "昼休み"
    elif t < dtime(15, 25):
        state, label = "afternoon", "後場"
    elif t < dtime(15, 30):
        state, label = "closing_auction", "クロージング・オークション"
    else:
        state, label = "closed", "大引け後"
    return {"state": state, "label": label, "holiday": None}


def next_trading_day(d):
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d
