"""
Quantitative Analysis & Predictive Signal Engine for Japan Stocks
Calculates technical indicators, multi-factor directional scores, pivot levels, and day-trading setups.
"""

import math
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

def clean_series(s):
    if isinstance(s, pd.DataFrame):
        return s.iloc[:, 0]
    return s

def calculate_indicators(df):
    """
    Computes technical indicators on OHLCV DataFrame.
    Expects columns: Open, High, Low, Close, Volume
    """
    if df is None or len(df) < 15:
        return None

    df = df.copy()
    close = df['Close']
    high = df['High']
    low = df['Low']
    vol = df['Volume']

    # EMAs
    df['EMA9'] = close.ewm(span=9, adjust=False).mean()
    df['EMA21'] = close.ewm(span=21, adjust=False).mean()
    df['EMA50'] = close.ewm(span=50, adjust=False).mean()

    # RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    
    # Simple Wilder's style smoothing
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50.0)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # Bollinger Bands (20, 2)
    sma20 = close.rolling(window=min(20, len(df)), min_periods=5).mean()
    std20 = close.rolling(window=min(20, len(df)), min_periods=5).std().fillna(close * 0.01)
    df['BB_Mid'] = sma20
    df['BB_Upper'] = sma20 + (2 * std20)
    df['BB_Lower'] = sma20 - (2 * std20)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']).fillna(0.02)
    df['BB_PercentB'] = ((close - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower']).replace(0, np.nan)).fillna(0.5)

    # ATR (14)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=min(14, len(df)), min_periods=3).mean().bfill().fillna(close * 0.015)

    # VWAP (if intraday with volume)
    if 'Volume' in df.columns and (vol > 0).any():
        typical_price = (high + low + close) / 3
        df['VWAP'] = (typical_price * vol).cumsum() / vol.cumsum().replace(0, np.nan)
        df['VWAP'] = df['VWAP'].bfill().fillna(close)
    else:
        df['VWAP'] = df['EMA21']

    # RVol (Relative Volume vs 20-period average)
    avg_vol20 = vol.rolling(window=20).mean().replace(0, np.nan)
    df['RVol'] = (vol / avg_vol20).fillna(1.0)

    return df

def calculate_pivot_points(prev_high, prev_low, prev_close):
    """Classic Floor Trader Pivot Points"""
    p = (prev_high + prev_low + prev_close) / 3.0
    r1 = (2 * p) - prev_low
    s1 = (2 * p) - prev_high
    r2 = p + (prev_high - prev_low)
    s2 = p - (prev_high - prev_low)
    return {
        "P": round(p, 1),
        "R1": round(r1, 1),
        "R2": round(r2, 1),
        "S1": round(s1, 1),
        "S2": round(s2, 1)
    }

def generate_directional_prediction(df, macro_context=None):
    """
    Multi-Factor Quantitative Predictive Model:
    Evaluates Trend (30%), Momentum (25%), Volatility/Breakout (20%), Volume (15%), and Macro (10%).
    Returns:
      - score: -100 to +100
      - signal: STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL
      - probability_up: e.g. 74.2%
      - setup: Day trade playbook recommendation
    """
    if df is None or len(df) < 5:
        return {
            "score": 0,
            "signal": "NEUTRAL",
            "confidence": 50.0,
            "probability_up": 50.0,
            "probability_down": 50.0,
            "factors": {},
            "setup": "Insufficient Data"
        }

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    close = float(latest['Close'])
    ema9 = float(latest['EMA9'])
    ema21 = float(latest['EMA21'])
    ema50 = float(latest['EMA50'])
    rsi = float(latest['RSI'])
    macd = float(latest['MACD'])
    macd_signal = float(latest['MACD_Signal'])
    macd_hist = float(latest['MACD_Hist'])
    prev_macd_hist = float(prev['MACD_Hist'])
    bb_upper = float(latest['BB_Upper'])
    bb_lower = float(latest['BB_Lower'])
    bb_pct_b = float(latest['BB_PercentB']) if not np.isnan(latest['BB_PercentB']) else 0.5
    atr = float(latest['ATR'])
    rvol = float(latest['RVol'])
    vwap = float(latest['VWAP'])

    # 1. Trend Factor (-30 to +30)
    trend_score = 0
    if ema9 > ema21 > ema50:
        trend_score += 20  # Bullish moving average stack
    elif ema9 < ema21 < ema50:
        trend_score -= 20  # Bearish moving average stack
    elif ema9 > ema21:
        trend_score += 10
    else:
        trend_score -= 10

    if close > vwap:
        trend_score += 10
    else:
        trend_score -= 10

    # 2. Momentum Factor (-25 to +25)
    momentum_score = 0
    # RSI evaluation
    if 50 <= rsi <= 68:
        momentum_score += 12  # Healthy bullish momentum
    elif rsi > 75:
        momentum_score -= 5   # Overbought caution for day trading
    elif 32 <= rsi < 50:
        momentum_score -= 10  # Bearish drift
    elif rsi < 28:
        momentum_score += 10  # Oversold bounce candidate

    # MACD histogram acceleration
    if macd > macd_signal:
        momentum_score += 8
        if macd_hist > prev_macd_hist:
            momentum_score += 5  # Accelerating
    else:
        momentum_score -= 8
        if macd_hist < prev_macd_hist:
            momentum_score -= 5

    # 3. Volatility & Breakout Factor (-20 to +20)
    vol_score = 0
    if bb_pct_b > 0.8:
        vol_score += 12  # Pushing upper band
    elif bb_pct_b < 0.2:
        vol_score -= 12  # Pushing lower band
    else:
        vol_score += 0

    # 4. Volume Factor (-15 to +15)
    # High volume reinforces the dominant direction
    volume_score = 0
    preliminary_direction = 1 if (trend_score + momentum_score) > 0 else -1
    if rvol >= 1.8:
        volume_score = preliminary_direction * 15
    elif rvol >= 1.2:
        volume_score = preliminary_direction * 10
    elif rvol < 0.8:
        volume_score = -preliminary_direction * 5  # Low volume divergence

    # 5. Macro Factor (-10 to +10)
    macro_score = 0
    if macro_context:
        nikkei_change = macro_context.get("nikkei_change_pct", 0)
        usdjpy_change = macro_context.get("usdjpy_change_pct", 0)
        
        # Nikkei alignment
        if nikkei_change > 0.5:
            macro_score += 5
        elif nikkei_change < -0.5:
            macro_score -= 5
            
        # USDJPY export tailwind
        if usdjpy_change > 0.3:
            macro_score += 5
        elif usdjpy_change < -0.3:
            macro_score -= 5

    total_score = trend_score + momentum_score + vol_score + volume_score + macro_score
    total_score = max(-100, min(100, total_score))

    # Convert to Win Probability via Sigmoid with center at 50%
    prob_up = 1.0 / (1.0 + math.exp(-total_score / 28.0))
    prob_up_pct = round(prob_up * 100, 1)
    prob_down_pct = round(100.0 - prob_up_pct, 1)

    # Classify Signal with authentic Japanese market marks
    if total_score >= 45:
        signal = "STRONG BUY"
        signal_jp = "強い買い"
        mark = "◎"
        action = "BUY"
        action_jp = "買いエントリー"
        setup = "順張りブレイクアウト（VWAP＆EMA9押し目追随）"
    elif total_score >= 15:
        signal = "BUY"
        signal_jp = "買い"
        mark = "○"
        action = "BUY"
        action_jp = "押し目買い"
        setup = "サポレジ押し目買い / EMA21リバウンド狙い"
    elif total_score <= -45:
        signal = "STRONG SELL"
        signal_jp = "強い売り"
        mark = "×"
        action = "SELL"
        action_jp = "空売りエントリー"
        setup = "下値支持線ブレイクダウン / EMA9下落追随"
    elif total_score <= -15:
        signal = "SELL"
        signal_jp = "売り"
        mark = "▼"
        action = "SELL"
        action_jp = "戻り売り"
        setup = "戻り高値売り / VWAP・レジスタンス反落"
    else:
        signal = "HOLD"
        signal_jp = "様子見"
        mark = "△"
        action = "HOLD"
        action_jp = "様子見 / 保有"
        setup = "保ち合いレンジ相場 — ブレイクアウト待機"

    # Day Trading Execution Plan (ATR-based dynamic brackets)
    atr_buffer = max(atr * 1.2, close * 0.005)
    
    if action == "BUY":
        entry_price = round(close, 1)
        stop_loss = round(close - atr_buffer, 1)
        target1 = round(close + (atr_buffer * 1.5), 1)
        target2 = round(close + (atr_buffer * 2.6), 1)
        risk = entry_price - stop_loss
        reward = target1 - entry_price
        rr_ratio = round(reward / risk, 2) if risk > 0 else 1.5
    elif action == "SELL":
        entry_price = round(close, 1)
        stop_loss = round(close + atr_buffer, 1)
        target1 = round(close - (atr_buffer * 1.5), 1)
        target2 = round(close - (atr_buffer * 2.6), 1)
        risk = stop_loss - entry_price
        reward = entry_price - target1
        rr_ratio = round(reward / risk, 2) if risk > 0 else 1.5
    else: # HOLD
        entry_price = round(close, 1)
        stop_loss = round(close - atr_buffer, 1)
        target1 = round(close + atr_buffer, 1)
        target2 = round(close + (atr_buffer * 2.0), 1)
        rr_ratio = 1.0

    return {
        "score": total_score,
        "signal": signal,
        "signal_jp": signal_jp,
        "mark": mark,
        "action": action,
        "action_jp": action_jp,
        "probability_up": prob_up_pct,
        "probability_down": prob_down_pct,
        "confidence": round(abs(prob_up_pct - 50.0) * 2, 1),
        "setup": setup,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_reward": f"1:{rr_ratio}",
        "factors": {
            "trend": trend_score,
            "momentum": momentum_score,
            "volatility": vol_score,
            "volume": volume_score,
            "macro": macro_score
        },
        "indicators": {
            "close": close,
            "ema9": round(ema9, 1),
            "ema21": round(ema21, 1),
            "ema50": round(ema50, 1),
            "rsi": round(rsi, 1),
            "macd": round(macd, 2),
            "macd_signal": round(macd_signal, 2),
            "macd_hist": round(macd_hist, 2),
            "atr": round(atr, 1),
            "rvol": round(rvol, 2),
            "vwap": round(vwap, 1),
            "bb_upper": round(bb_upper, 1),
            "bb_lower": round(bb_lower, 1)
        }
    }
