from datetime import datetime

import numpy as np
import pandas as pd

import kronos_feed
import kronos_intraday as ki
from market_rules import JST


def test_parse_keeps_well_formed_forecasts():
    data = {
        "generated_at": "2026-10-19T10:30:00+09:00", "interval": "15m", "horizon_bars": 4,
        "forecasts": {
            "6501.T": {"direction": "down", "expected_move_pct": -0.21, "path_agreement": 0.875,
                       "target_bar": "2026-10-19T11:15:00+09:00"},
            "7203.T": {"direction": "sideways"},
            "6758.T": "junk",
        },
    }
    feed = kronos_feed.parse(data)
    assert list(feed["forecasts"]) == ["6501.T"]
    assert feed["forecasts"]["6501.T"]["expected_move_pct"] == -0.21
    assert feed["horizon_bars"] == 4


def test_fetch_failure_returns_empty_feed():
    feed = kronos_feed.fetch(url="http://127.0.0.1:9/nope.json", timeout=1)
    assert feed["forecasts"] == {}
    assert "error" in feed


def test_future_bars_skip_lunch_and_overnight():
    assert ki.future_bar_times(datetime(2026, 10, 19, 10, 45)) == [
        datetime(2026, 10, 19, 11, 0), datetime(2026, 10, 19, 11, 15),
        datetime(2026, 10, 19, 12, 30), datetime(2026, 10, 19, 12, 45)]
    # Friday close -> Monday morning
    assert ki.future_bar_times(datetime(2026, 10, 16, 15, 15))[0] == datetime(2026, 10, 19, 9, 0)


def _bars(n, end):
    times = []
    d = end.date()
    while len(times) < n:
        times = [datetime(d.year, d.month, d.day, h, m) for h, m in ki.SESSION_SLOTS if datetime(d.year, d.month, d.day, h, m) <= end] + times
        d = pd.Timestamp(d) - pd.tseries.offsets.BDay(1)
        d = d.date()
    times = times[-n:]
    close = np.linspace(100, 110, n)
    idx = pd.DatetimeIndex(times).tz_localize("Asia/Tokyo")
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0}, index=idx)


class FakePredictor:
    """Every path ends 1% above the input's last close."""

    def predict_batch(self, df_list, x_timestamp_list, y_timestamp_list, pred_len, **kw):
        return [pd.DataFrame({"close": [df["close"].iloc[-1] * 1.01] * pred_len}) for df in df_list]


def test_run_drops_forming_bar_and_forecasts_one_hour():
    now = datetime(2026, 10, 19, 10, 50, tzinfo=JST)
    hist = _bars(300, datetime(2026, 10, 19, 10, 30))
    feed = ki.run({"6501.T": hist, "7203.T": hist.tail(50)}, FakePredictor(), now=now)
    fc = feed["forecasts"]["6501.T"]
    assert fc["last_bar"] == "2026-10-19T10:15:00+09:00"   # 10:30 bar still forming with the 20 min delay
    assert fc["target_bar"] == "2026-10-19T11:15:00+09:00"
    assert fc["direction"] == "up" and abs(fc["expected_move_pct"] - 1.0) < 1e-6
    assert fc["path_agreement"] == 1.0
    assert feed["stats"]["skipped"] == {"short_history": 1}
