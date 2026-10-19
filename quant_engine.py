"""
Quantitative Analysis & Signal Engine for Japan Stocks
Computes intraday-aware indicators, fuses rule-based agent scores, and builds
tick-rounded day-trade brackets. Every indicator is causal (uses only bars up to
and including the current one) so the same code drives the live view and the backtest.
"""

import json
import os
import numpy as np
import pandas as pd

from agents import default_fusion
from market_rules import JST, round_to_tick, price_limits

MIN_BARS = 60
OPENING_RANGE_MINUTES = 30
CALIBRATION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")

SETUPS = {
    "STRONG BUY": ("順張りブレイクアウト（VWAP上・ORブレイク追随）", "買いエントリー"),
    "BUY": ("押し目買い（VWAP / EMA21 反発狙い）", "押し目買い"),
    "STRONG SELL": ("下値ブレイクダウン（VWAP下・OR安値割れ追随）", "空売りエントリー"),
    "SELL": ("戻り売り（VWAP / レジスタンス反落）", "戻り売り"),
    "HOLD": ("レンジ相場 — ブレイク待ち", "様子見"),
}


def _to_jst_index(df):
    idx = df.index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(JST)
    df = df.copy()
    df.index = idx
    return df


def infer_is_intraday(df):
    if len(df) < 3:
        return False
    step = pd.Series(df.index).diff().dropna().median()
    return step < pd.Timedelta(hours=12)


def calculate_indicators(df, intraday=None):
    """
    Computes indicators on an OHLCV DataFrame (columns Open, High, Low, Close, Volume).
    Intraday frames get session-reset VWAP (+σ bands), opening range, running session
    high/low, prior-session levels and time-of-day relative volume.
    """
    if df is None or len(df) < 15:
        return None

    df = _to_jst_index(df.dropna(subset=["Open", "High", "Low", "Close"]))
    if intraday is None:
        intraday = infer_is_intraday(df)
    df["Volume"] = df["Volume"].fillna(0)
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    df["EMA9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()
    df["EMA21_Slope"] = df["EMA21"].diff(3) / 3

    # RSI (14), Wilder smoothing
    delta = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = (100 - 100 / (1 + rs)).fillna(50.0)

    # MACD (12, 26, 9)
    df["MACD"] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # Bollinger Bands (20, 2) + squeeze = width in the bottom 20% of the last 120 bars
    sma20 = close.rolling(20, min_periods=20).mean()
    std20 = close.rolling(20, min_periods=20).std()
    df["BB_Upper"] = sma20 + 2 * std20
    df["BB_Lower"] = sma20 - 2 * std20
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / sma20
    df["BB_PercentB"] = (close - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)
    width_rank = df["BB_Width"].rolling(120, min_periods=40).rank(pct=True)
    df["Squeeze"] = (width_rank.shift(1) <= 0.2)

    prev_close = close.shift(1)
    if intraday:
        session = pd.Series(df.index.date, index=df.index)
        new_session = session.ne(session.shift(1))
        # Overnight gaps are not intraday volatility: first bar of a session uses its own range
        prev_close = prev_close.where(~new_session)
        df["Session"] = session
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    if intraday:
        _add_session_features(df)
    else:
        df["VWAP"] = np.nan
        df["VWAP_SD"] = np.nan
        avg_vol20 = vol.rolling(20, min_periods=10).mean().shift(1)
        df["RVol"] = vol / avg_vol20.replace(0, np.nan)
        df["Prev_Day_High"] = high.shift(1)
        df["Prev_Day_Low"] = low.shift(1)
        df["Prev_Day_Close"] = close.shift(1)
        df["OR_High"] = np.nan
        df["OR_Low"] = np.nan
        df["OR_Complete"] = False
        df["Session_Open"] = df["Open"]

    df.attrs["intraday"] = bool(intraday)
    return df


def _add_session_features(df):
    g = df.groupby("Session", sort=False)
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"]
    cum_vol = g["Volume"].cumsum()
    cum_pv = (tp * vol).groupby(df["Session"], sort=False).cumsum()
    cum_p2v = (tp * tp * vol).groupby(df["Session"], sort=False).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    var = (cum_p2v / cum_vol.replace(0, np.nan) - vwap ** 2).clip(lower=0)
    df["VWAP"] = vwap.fillna(tp)
    df["VWAP_SD"] = np.sqrt(var).fillna(0)

    df["Session_Open"] = g["Open"].transform("first")
    df["Session_High"] = g["High"].cummax()
    df["Session_Low"] = g["Low"].cummin()

    # Opening range: running high/low during the first N minutes, frozen afterwards
    minutes = (df.index.hour * 60 + df.index.minute) - (9 * 60)
    in_or = pd.Series(minutes < OPENING_RANGE_MINUTES, index=df.index)
    or_high = df["High"].where(in_or).groupby(df["Session"], sort=False).cummax()
    or_low = df["Low"].where(in_or).groupby(df["Session"], sort=False).cummin()
    df["OR_High"] = or_high.groupby(df["Session"], sort=False).ffill()
    df["OR_Low"] = or_low.groupby(df["Session"], sort=False).ffill()
    df["OR_Complete"] = ~in_or

    # Prior-session levels
    daily = g.agg(H=("High", "max"), L=("Low", "min"), C=("Close", "last")).shift(1)
    df["Prev_Day_High"] = df["Session"].map(daily["H"])
    df["Prev_Day_Low"] = df["Session"].map(daily["L"])
    df["Prev_Day_Close"] = df["Session"].map(daily["C"])

    # Time-of-day RVol: today's cumulative volume vs. the average cumulative volume
    # at the same bar of the previous 10 sessions (avoids the open-auction volume spike bias)
    bar_idx = g.cumcount()
    hist = pd.DataFrame({"bar": bar_idx, "cum": cum_vol})
    baseline = hist.groupby("bar")["cum"].transform(lambda s: s.shift(1).rolling(10, min_periods=2).mean())
    df["RVol"] = cum_vol / baseline.replace(0, np.nan)


def build_features(df, i=-1, macro_context=None, meta=None):
    row = df.iloc[i]
    prev = df.iloc[i - 1] if len(df) > 1 else row

    def g(col, r=row):
        v = r.get(col, np.nan)
        return float(v) if v is not None and not pd.isna(v) else np.nan

    f = {
        "intraday": df.attrs.get("intraday", False),
        "close": g("Close"),
        "ema9": g("EMA9"), "ema21": g("EMA21"), "ema50": g("EMA50"),
        "ema21_slope": g("EMA21_Slope"),
        "rsi": g("RSI"),
        "macd": g("MACD"), "macd_signal": g("MACD_Signal"),
        "macd_hist": g("MACD_Hist"), "prev_macd_hist": g("MACD_Hist", prev),
        "bb_upper": g("BB_Upper"), "bb_lower": g("BB_Lower"), "bb_pct_b": g("BB_PercentB"),
        "squeeze": bool(row.get("Squeeze", False)),
        "atr": g("ATR"),
        "rvol": g("RVol"),
        "vwap": g("VWAP"), "vwap_sd": g("VWAP_SD"),
        "or_high": g("OR_High"), "or_low": g("OR_Low"),
        "or_complete": bool(row.get("OR_Complete", False)),
        "prev_day_high": g("Prev_Day_High"), "prev_day_low": g("Prev_Day_Low"),
        "prev_day_close": g("Prev_Day_Close"),
        "session_open": g("Session_Open"),
        "fx_beta": (meta or {}).get("fx_beta", 0.0),
    }
    if macro_context and not macro_context.get("error"):
        f["nikkei_chg"] = macro_context.get("nikkei_change_pct")
        f["usdjpy_chg"] = macro_context.get("usdjpy_change_pct")
    return f


def calculate_pivot_points(prev_high, prev_low, prev_close, topix500=False):
    """Classic floor-trader pivots, snapped to the tick grid."""
    p = (prev_high + prev_low + prev_close) / 3.0
    levels = {
        "P": p,
        "R1": 2 * p - prev_low,
        "S1": 2 * p - prev_high,
        "R2": p + (prev_high - prev_low),
        "S2": p - (prev_high - prev_low),
    }
    return {k: round_to_tick(v, topix500) for k, v in levels.items()}


_calibration_cache = {"mtime": None, "data": None}


def load_calibration():
    try:
        mtime = os.path.getmtime(CALIBRATION_PATH)
    except OSError:
        return None
    if _calibration_cache["mtime"] != mtime:
        with open(CALIBRATION_PATH, encoding="utf-8") as fh:
            _calibration_cache["data"] = json.load(fh)
        _calibration_cache["mtime"] = mtime
    return _calibration_cache["data"]


def calibrated_probability(score, interval):
    """
    Empirical P(price higher after the calibration horizon) for this score bucket,
    as measured by backtest.py. Returns None if no backtest has been run for this
    interval or the bucket has too few samples to mean anything.
    """
    cal = load_calibration()
    if not cal or interval not in cal:
        return None
    block = cal[interval]
    for b in block["buckets"]:
        if b["lo"] <= score < b["hi"] or (b["hi"] >= 100 and score >= b["lo"]):
            if b["n"] < block.get("min_samples", 50):
                return None
            return {"p_up": b["p_up"], "n": b["n"], "horizon_bars": block["horizon_bars"],
                    "avg_ret_pct": b.get("avg_ret_pct"), "base_rate_up": block.get("base_rate_up")}
    return None


def signal_hit_rate(action, prob):
    """
    How often the signal's own direction was right (P(up) for BUY, P(down) for SELL), in %,
    and its edge over the unconditional base rate for that direction, in percentage points.
    (None, None) for HOLD or when uncalibrated; edge is None if the base rate is missing.
    """
    if not prob or action not in ("BUY", "SELL"):
        return None, None
    hit = prob["p_up"] if action == "BUY" else 1 - prob["p_up"]
    base = prob.get("base_rate_up")
    if base is not None and action == "SELL":
        base = 1 - base
    edge = round((hit - base) * 100, 1) if base is not None else None
    return round(hit * 100, 1), edge


def build_brackets(action, f, topix500=False, stop_atr=1.2, t1_r=1.5, t2_r=2.6):
    """ATR stop and R-multiple targets, rounded to valid ticks and clipped to the daily price limits."""
    close, atr = f["close"], f["atr"]
    if action not in ("BUY", "SELL") or not np.isfinite(atr) or atr <= 0:
        return None
    buffer = max(atr * stop_atr, close * 0.003)
    base = f["prev_day_close"] if np.isfinite(f.get("prev_day_close", np.nan)) else close
    limits = price_limits(base)
    long_ = action == "BUY"
    sign = 1 if long_ else -1

    entry = round_to_tick(close, topix500)
    stop = round_to_tick(entry - sign * buffer, topix500, "down" if long_ else "up")
    risk = abs(entry - stop)
    t1 = entry + sign * risk * t1_r
    t2 = entry + sign * risk * t2_r
    # Targets can't trade beyond limit-up / limit-down
    if long_:
        t1, t2 = min(t1, limits["limit_up"]), min(t2, limits["limit_up"])
    else:
        t1, t2 = max(t1, limits["limit_down"]), max(t2, limits["limit_down"])
    t1 = round_to_tick(t1, topix500, "down" if long_ else "up")
    t2 = round_to_tick(t2, topix500, "down" if long_ else "up")
    rr = round(abs(t1 - entry) / risk, 2) if risk > 0 else 0.0
    return {"entry_price": entry, "stop_loss": stop, "target1": t1, "target2": t2,
            "risk_reward": f"1:{rr}", "risk_per_share": round(risk, 1)}


def generate_directional_prediction(df, macro_context=None, meta=None, interval="15m"):
    """
    Fuses agent scores on the latest bar of an indicator frame.
    Returns score (-100..100), signal, action, brackets (None when HOLD),
    calibrated probability (None until backtest.py has been run), agent outputs and warnings.
    """
    meta = meta or {}
    topix500 = meta.get("topix500", False)
    if df is None or len(df) < MIN_BARS:
        return {
            "score": 0, "signal": "HOLD", "signal_jp": "様子見", "mark": "△",
            "action": "HOLD", "action_jp": "様子見", "action_en": "HOLD",
            "probability_up": None, "probability_down": None, "probability_signal": None, "signal_edge_pp": None,
            "probability_source": "insufficient data",
            "confidence": 0.0, "agents": [], "setup": "データ不足 (Insufficient data)",
            "brackets": None, "factors": {}, "indicators": {}, "levels": {},
            "warnings": [f"Need at least {MIN_BARS} bars to score"],
        }

    f = build_features(df, -1, macro_context, meta)
    result = default_fusion().run_all(f)
    score, signal, action = result["final_score"], result["final_signal"], result["final_action"]
    setup, action_jp = SETUPS[signal]

    prob = calibrated_probability(score, interval)
    hit_rate, edge_pp = signal_hit_rate(action, prob)
    warnings = []
    if not f["intraday"]:
        warnings.append("日足ベースのシグナル (Daily-bar signal — swing context, not an intraday trigger)")

    base = f["prev_day_close"] if np.isfinite(f["prev_day_close"]) else f["close"]
    limits = price_limits(base)
    if f["atr"] > 0:
        if (limits["limit_up"] - f["close"]) < 2 * f["atr"]:
            warnings.append("ストップ高接近 (Within 2 ATR of limit-up)")
        if (f["close"] - limits["limit_down"]) < 2 * f["atr"]:
            warnings.append("ストップ安接近 (Within 2 ATR of limit-down)")
    if np.isfinite(f["rvol"]) and f["rvol"] < 0.5:
        warnings.append("出来高閑散 (RVol < 0.5x — thin liquidity)")

    def r1(x, nd=1):
        return round(float(x), nd) if x is not None and np.isfinite(x) else None

    return {
        "score": score,
        "signal": signal,
        "signal_jp": result["final_signal_jp"],
        "mark": result["final_mark"],
        "action": action,
        "action_jp": action_jp,
        "action_en": action,
        "probability_up": round(prob["p_up"] * 100, 1) if prob else None,
        "probability_down": round((1 - prob["p_up"]) * 100, 1) if prob else None,
        "probability_signal": hit_rate,
        "signal_edge_pp": edge_pp,
        "probability_source": (f"backtest n={prob['n']}, {prob['horizon_bars']}-bar horizon" if prob else "uncalibrated"),
        "confidence": result["agreement"],
        "agents": result["agents"],
        "setup": setup,
        "brackets": build_brackets(action, f, topix500),
        "factors": {a["agent"]: a["score"] for a in result["agents"]},
        "indicators": {
            "close": r1(f["close"]), "ema9": r1(f["ema9"]), "ema21": r1(f["ema21"]), "ema50": r1(f["ema50"]),
            "rsi": r1(f["rsi"]), "macd": r1(f["macd"], 2), "macd_signal": r1(f["macd_signal"], 2),
            "macd_hist": r1(f["macd_hist"], 2), "atr": r1(f["atr"]), "rvol": r1(f["rvol"], 2),
            "vwap": r1(f["vwap"]), "vwap_sd": r1(f["vwap_sd"]),
            "bb_upper": r1(f["bb_upper"]), "bb_lower": r1(f["bb_lower"]),
        },
        "levels": {
            "vwap": r1(f["vwap"]),
            "vwap_upper1": r1(f["vwap"] + f["vwap_sd"]) if f["intraday"] else None,
            "vwap_lower1": r1(f["vwap"] - f["vwap_sd"]) if f["intraday"] else None,
            "vwap_upper2": r1(f["vwap"] + 2 * f["vwap_sd"]) if f["intraday"] else None,
            "vwap_lower2": r1(f["vwap"] - 2 * f["vwap_sd"]) if f["intraday"] else None,
            "or_high": r1(f["or_high"]), "or_low": r1(f["or_low"]),
            "or_complete": f["or_complete"],
            "prev_day_high": r1(f["prev_day_high"]), "prev_day_low": r1(f["prev_day_low"]),
            "prev_day_close": r1(f["prev_day_close"]),
            "session_open": r1(f["session_open"]),
            "limit_up": limits["limit_up"], "limit_down": limits["limit_down"],
        },
        "warnings": warnings,
    }
