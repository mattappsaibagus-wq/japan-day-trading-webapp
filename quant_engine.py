"""
Quantitative Analysis & Predictive Signal Engine for Japan Stocks
Calculates technical indicators, multi-agent directional scores, pivot levels, and day-trading setups.
"""

import math
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# Import agents
from agents.kronos_agent import KronosAgent
from agents.trend_agent import TrendAgent
from agents.momentum_agent import MomentumAgent
from agents.breakout_agent import BreakoutAgent
from agents.macro_agent import MacroAgent
from agents.fusion import AgentFusion

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
    Multi-Agent Quantitative Predictive Model:
    Uses Kronos, Trend, Momentum, Breakout, and Macro agents to generate signals.
    Kronos agent is weighted highest for day/overnight prediction.
    Returns:
      - score: -100 to +100 (fused agent score)
      - signal: STRONG BUY / BUY / HOLD / SELL / STRONG SELL
      - probability_up: e.g. 74.2%
      - agents: individual agent outputs
      - setup: Day trade playbook recommendation
    """
    if df is None or len(df) < 5:
        return {
            "score": 0,
            "signal": "HOLD",
            "signal_jp": "様子見",
            "mark": "△",
            "action": "HOLD",
            "action_jp": "様子見 / 保有",
            "probability_up": 50.0,
            "probability_down": 50.0,
            "confidence": 0.0,
            "agents": [],
            "setup": "Insufficient Data",
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "target1": 0.0,
            "target2": 0.0,
            "risk_reward": "1:0.0",
            "factors": {},
            "indicators": {}
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

    # Prepare features for agents
    features = {
        'close': close,
        'ema9': ema9,
        'ema21': ema21,
        'ema50': ema50,
        'rsi': rsi,
        'macd': macd,
        'macd_signal': macd_signal,
        'macd_hist': macd_hist,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'bb_pct_b': bb_pct_b,
        'atr': atr,
        'rvol': rvol,
        'vwap': vwap,
        'prev_close': float(prev['Close']),
    }

    # Add macro context if provided
    if macro_context:
        features.update({
            'nikkei_chg': macro_context.get("nikkei_change_pct", 0.0),
            'usdjpy_chg': macro_context.get("usdjpy_change_pct", 0.0),
        })

    # Initialize agents and run fusion
    fusion = AgentFusion([
        KronosAgent(weight=1.0),      # Kronos gets highest weight for day trading
        TrendAgent(weight=0.6),
        MomentumAgent(weight=0.6),
        BreakoutAgent(weight=0.5),
        MacroAgent(weight=0.4),
    ])

    result = fusion.run_all(features)

    # Format result to match existing API
    signal = result['final_signal']
    signal_jp = result['final_signal_jp']
    action = result['final_action']
    mark = result['final_mark']
    score = result['final_score']
    probability_up = result['probability_up']
    probability_down = result['probability_down']
    confidence = result['confidence']

    # Setup text based on final signal (keeping some of the original setup logic)
    if signal == "STRONG BUY":
        setup = "順張りブレイクアウト（VWAP＆EMA9押し目追随）"
        action_jp = "買いエントリー"
    elif signal == "BUY":
        setup = "サポレジ押し目買い / EMA21リバウンド狙い"
        action_jp = "押し目買い"
    elif signal == "STRONG SELL":
        setup = "下値支持線ブレイクダウン / EMA9下落追随"
        action_jp = "空売りエントリー"
    elif signal == "SELL":
        setup = "戻り高値売り / VWAP・レジスタンス反落"
        action_jp = "戻り売り"
    else:  # HOLD
        setup = "保ち合いレンジ相場 — ブレイクアウト待機"
        action_jp = "様子見 / 保有"

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

    # Return formatted result
    # Map signal to English action code for API filtering
    signal_to_action = {
        "STRONG BUY": "BUY",
        "BUY": "BUY",
        "HOLD": "HOLD",
        "SELL": "SELL",
        "STRONG SELL": "SELL"
    }
    action_en = signal_to_action.get(signal, "HOLD")
    
    return {
        "score": score,
        "signal": signal,
        "signal_jp": signal_jp,
        "mark": mark,
        "action": action,
        "action_jp": action_jp,
        "action_en": action_en,  # English action code for filtering
        "probability_up": probability_up,
        "probability_down": probability_down,
        "confidence": confidence,
        "agents": result['agents'],  # Include individual agent outputs
        "setup": setup,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_reward": f"1:{rr_ratio}",
        "factors": {
            # Keep the old factors structure for compatibility, but now from agents
            "kronos": next((a['score'] for a in result['agents'] if a['agent'] == 'kronos'), 0),
            "trend": next((a['score'] for a in result['agents'] if a['agent'] == 'trend'), 0),
            "momentum": next((a['score'] for a in result['agents'] if a['agent'] == 'momentum'), 0),
            "breakout": next((a['score'] for a in result['agents'] if a['agent'] == 'breakout'), 0),
            "macro": next((a['score'] for a in result['agents'] if a['agent'] == 'macro'), 0),
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