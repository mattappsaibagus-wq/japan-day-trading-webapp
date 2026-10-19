import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_session_bars(n_sessions=30, start_price=3000.0, drift=0.0, seed=0, interval_min=15):
    """Synthetic TSE 15m bars: 09:00-11:30 and 12:30-15:30 JST, business days only."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2026-08-03", periods=n_sessions)
    stamps = []
    for d in days:
        for start, end in (("09:00", "11:30"), ("12:30", "15:30")):
            stamps.extend(pd.date_range(f"{d.date()} {start}", f"{d.date()} {end}",
                                        freq=f"{interval_min}min", inclusive="left"))
    idx = pd.DatetimeIndex(stamps).tz_localize("Asia/Tokyo")
    rets = rng.normal(drift, 0.003, len(idx))
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, len(idx)))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, len(idx)))
    vol = rng.integers(10_000, 50_000, len(idx)).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


@pytest.fixture
def bars():
    return make_session_bars()
