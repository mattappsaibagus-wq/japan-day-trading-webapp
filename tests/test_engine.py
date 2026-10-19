import numpy as np
import pandas as pd

from conftest import make_session_bars
from market_rules import tick_size
from quant_engine import calculate_indicators, generate_directional_prediction


def test_vwap_resets_each_session(bars):
    calc = calculate_indicators(bars, intraday=True)
    first_bars = calc.groupby("Session").head(1)
    tp = (first_bars["High"] + first_bars["Low"] + first_bars["Close"]) / 3
    assert np.allclose(first_bars["VWAP"], tp)


def test_indicators_are_causal(bars):
    """Values at bar i must not change when future bars are appended."""
    full = calculate_indicators(bars, intraday=True)
    cut = calculate_indicators(bars.iloc[:400], intraday=True)
    cols = ["EMA21", "RSI", "MACD_Hist", "ATR", "VWAP", "VWAP_SD", "RVol", "OR_High", "Prev_Day_Close", "BB_PercentB"]
    pd.testing.assert_frame_equal(full[cols].iloc[:400], cut[cols], check_freq=False)


def test_opening_range_frozen_after_30min(bars):
    calc = calculate_indicators(bars, intraday=True)
    day = calc[calc["Session"] == calc["Session"].iloc[-1]]
    assert day["OR_High"].iloc[2:].nunique() == 1
    assert day["OR_High"].iloc[-1] == day["High"].iloc[:2].max()
    assert not day["OR_Complete"].iloc[0] and day["OR_Complete"].iloc[2]


def test_prev_day_levels(bars):
    calc = calculate_indicators(bars, intraday=True)
    sessions = calc["Session"].unique()
    prev = calc[calc["Session"] == sessions[-2]]
    today = calc[calc["Session"] == sessions[-1]]
    assert today["Prev_Day_High"].iloc[0] == prev["High"].max()
    assert today["Prev_Day_Close"].iloc[0] == prev["Close"].iloc[-1]


def test_prediction_brackets_on_tick_grid():
    for drift, expected in ((0.0015, "BUY"), (-0.0015, "SELL")):
        calc = calculate_indicators(make_session_bars(drift=drift, seed=3), intraday=True)
        pred = generate_directional_prediction(calc, None, {"topix500": False})
        assert pred["action"] == expected
        b = pred["brackets"]
        for k in ("entry_price", "stop_loss", "target1", "target2"):
            t = tick_size(b[k])
            assert abs(b[k] / t - round(b[k] / t)) < 1e-6, (k, b[k])
        if expected == "BUY":
            assert b["stop_loss"] < b["entry_price"] < b["target1"] <= b["target2"]
        else:
            assert b["stop_loss"] > b["entry_price"] > b["target1"] >= b["target2"]


def test_hold_has_no_brackets_and_uncalibrated_probability(bars, monkeypatch):
    import quant_engine
    monkeypatch.setattr(quant_engine, "CALIBRATION_PATH", "/nonexistent.json")
    calc = calculate_indicators(bars, intraday=True)
    pred = generate_directional_prediction(calc, None, {})
    assert pred["probability_up"] is None and pred["probability_source"] == "uncalibrated"
    if pred["action"] == "HOLD":
        assert pred["brackets"] is None


def test_daily_frame_disables_vwap_agent(bars):
    daily = bars.resample("1D").agg({"Open": "first", "High": "max", "Low": "min",
                                     "Close": "last", "Volume": "sum"}).dropna()
    daily = pd.concat([daily] * 3)
    daily.index = pd.bdate_range("2026-01-05", periods=len(daily)).tz_localize("Asia/Tokyo")
    calc = calculate_indicators(daily, intraday=False)
    pred = generate_directional_prediction(calc, None, {}, "1d")
    vwap = next(a for a in pred["agents"] if a["agent"] == "vwap")
    assert not vwap["active"]
    assert any("Daily-bar" in w for w in pred["warnings"])
