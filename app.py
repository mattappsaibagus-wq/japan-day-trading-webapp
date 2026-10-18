"""
Flask Backend for Japan Day Trading Terminal
Serves real-time data, technical indicators, predictive quant models, and day-trade execution plans.
"""

import time
import logging
from flask import Flask, render_template, jsonify, request
import yfinance as yf
import pandas as pd
import numpy as np

from universe import STOCKS_UNIVERSE, MACRO_ASSETS
from quant_engine import calculate_indicators, generate_directional_prediction, calculate_pivot_points

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("japan-trading-app")

app = Flask(__name__)

# In-memory cache to stay fast and avoid rate-limits
CACHE = {
    "macro": {"timestamp": 0, "data": None},
    "screener": {"timestamp": 0, "data": None},
    "stocks": {} # symbol -> {timestamp, data}
}
CACHE_TTL_MACRO = 60      # 1 minute
CACHE_TTL_SCREENER = 120   # 2 minutes
CACHE_TTL_STOCK = 60      # 1 minute

def get_macro_context():
    now = time.time()
    if CACHE["macro"]["data"] and (now - CACHE["macro"]["timestamp"] < CACHE_TTL_MACRO):
        return CACHE["macro"]["data"]

    macro_data = {}
    try:
        tickers = [m["symbol"] for m in MACRO_ASSETS.values()]
        data = yf.download(tickers, period="5d", interval="1d", progress=False)
        close = data['Close']

        # Nikkei 225
        if '^N225' in close.columns:
            n225 = close['^N225'].dropna()
            if len(n225) >= 2:
                curr = float(n225.iloc[-1])
                prev = float(n225.iloc[-2])
                chg = curr - prev
                chg_pct = (chg / prev) * 100
                macro_data["nikkei"] = {
                    "price": round(curr, 2),
                    "change": round(chg, 2),
                    "change_pct": round(chg_pct, 2)
                }
                macro_data["nikkei_change_pct"] = chg_pct

        # USD/JPY
        if 'JPY=X' in close.columns:
            jpy = close['JPY=X'].dropna()
            if len(jpy) >= 2:
                curr = float(jpy.iloc[-1])
                prev = float(jpy.iloc[-2])
                chg = curr - prev
                chg_pct = (chg / prev) * 100
                macro_data["usdjpy"] = {
                    "price": round(curr, 3),
                    "change": round(chg, 3),
                    "change_pct": round(chg_pct, 2)
                }
                macro_data["usdjpy_change_pct"] = chg_pct

        # Market Regime
        nikkei_pct = macro_data.get("nikkei_change_pct", 0)
        usdjpy_pct = macro_data.get("usdjpy_change_pct", 0)
        if nikkei_pct > 0.5 and usdjpy_pct > 0.2:
            regime = "Risk-On (Export Tailwind)"
            bias = "BULLISH"
        elif nikkei_pct > 0.2:
            regime = "Mildly Bullish"
            bias = "BULLISH"
        elif nikkei_pct < -0.5:
            regime = "Risk-Off (Caution / Selective Shorts)"
            bias = "BEARISH"
        else:
            regime = "Neutral / Range-Bound"
            bias = "NEUTRAL"

        macro_data["regime"] = regime
        macro_data["bias"] = bias
        CACHE["macro"]["data"] = macro_data
        CACHE["macro"]["timestamp"] = now
    except Exception as e:
        logger.error(f"Error fetching macro: {e}")
        if not CACHE["macro"]["data"]:
            macro_data = {
                "nikkei": {"price": 39500.0, "change": 180.0, "change_pct": 0.46},
                "usdjpy": {"price": 155.20, "change": 0.35, "change_pct": 0.23},
                "regime": "Moderate Bullish",
                "bias": "BULLISH",
                "nikkei_change_pct": 0.46,
                "usdjpy_change_pct": 0.23
            }
            CACHE["macro"]["data"] = macro_data

    return CACHE["macro"]["data"]

def format_ticker_symbol(code_or_symbol):
    code = code_or_symbol.strip().upper()
    if not code.endswith(".T") and not code.startswith("^") and "=" not in code:
        code = f"{code}.T"
    return code

@app.route("/")
def index():
    return render_template("index.html", stocks=STOCKS_UNIVERSE)

@app.route("/api/macro")
def api_macro():
    return jsonify(get_macro_context())

@app.route("/api/screener")
def api_screener():
    now = time.time()
    cap_filter = request.args.get("cap", "all").lower()

    if CACHE["screener"]["data"] and (now - CACHE["screener"]["timestamp"] < CACHE_TTL_SCREENER):
        data = CACHE["screener"]["data"]
    else:
        macro = get_macro_context()
        symbols = [s["symbol"] for s in STOCKS_UNIVERSE]
        
        # Batch download daily data
        try:
            batch = yf.download(symbols, period="30d", interval="1d", progress=False, group_by="ticker")
        except Exception as e:
            logger.error(f"Batch fetch error: {e}")
            batch = {}

        results = []
        for meta in STOCKS_UNIVERSE:
            sym = meta["symbol"]
            try:
                if sym in batch:
                    df = batch[sym].dropna(how="all")
                else:
                    t = yf.Ticker(sym)
                    df = t.history(period="30d", interval="1d")

                if len(df) < 5:
                    continue

                df_calc = calculate_indicators(df)
                pred = generate_directional_prediction(df_calc, macro)
                
                curr_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2])
                chg = curr_price - prev_price
                chg_pct = (chg / prev_price) * 100

                rvol = pred["indicators"]["rvol"]
                rsi = pred["indicators"]["rsi"]

                results.append({
                    "symbol": sym,
                    "code": meta["code"],
                    "name": meta["name"],
                    "name_jp": meta["name_jp"],
                    "cap": meta["cap"],
                    "sector": meta["sector"],
                    "price": round(curr_price, 1),
                    "change": round(chg, 1),
                    "change_pct": round(chg_pct, 2),
                    "rvol": rvol,
                    "rsi": rsi,
                    "score": pred["score"],
                    "signal": pred["signal"],
                    "action": pred["action"],
                    "prob_up": pred["probability_up"],
                    "prob_down": pred["probability_down"],
                    "setup": pred["setup"]
                })
            except Exception as ex:
                logger.warning(f"Error analyzing {sym}: {ex}")

        # Sort by absolute prediction score & momentum
        results.sort(key=lambda x: abs(x["score"]), reverse=True)
        CACHE["screener"]["data"] = results
        CACHE["screener"]["timestamp"] = now
        data = results

    # Apply cap filter if requested
    if cap_filter != "all":
        data = [d for d in data if d["cap"].lower() == cap_filter]

    return jsonify({"stocks": data, "count": len(data)})

@app.route("/api/stock/<symbol>")
def api_stock_detail(symbol):
    sym = format_ticker_symbol(symbol)
    interval = request.args.get("interval", "15m") # 15m or 1d
    period = "5d" if interval in ["5m", "15m"] else "60d"

    macro = get_macro_context()
    
    try:
        t = yf.Ticker(sym)
        # Intraday / timeframe candles
        df_chart = t.history(period=period, interval=interval)
        if len(df_chart) == 0:
            # fallback to 1d
            df_chart = t.history(period="60d", interval="1d")

        # Daily candles for robust indicators and pivots
        df_daily = t.history(period="60d", interval="1d")
        df_daily_calc = calculate_indicators(df_daily)
        pred = generate_directional_prediction(df_daily_calc, macro)

        # Pivot points from prior complete daily session
        if len(df_daily) >= 2:
            prev_row = df_daily.iloc[-2]
            pivots = calculate_pivot_points(float(prev_row['High']), float(prev_row['Low']), float(prev_row['Close']))
        else:
            cur = float(df_daily['Close'].iloc[-1])
            pivots = calculate_pivot_points(cur*1.01, cur*0.99, cur)

        # Format candles for chart
        candles = []
        for idx, row in df_chart.iterrows():
            # handle timestamp
            if hasattr(idx, 'timestamp'):
                ts = int(idx.timestamp())
            else:
                ts = int(time.mktime(idx.timetuple()))

            candles.append({
                "time": ts,
                "open": round(float(row['Open']), 1),
                "high": round(float(row['High']), 1),
                "low": round(float(row['Low']), 1),
                "close": round(float(row['Close']), 1),
                "volume": int(row['Volume'])
            })

        # Match metadata
        meta = next((s for s in STOCKS_UNIVERSE if s["symbol"] == sym), None)
        if not meta:
            meta = {
                "symbol": sym,
                "code": sym.replace(".T", ""),
                "name": t.info.get("shortName", sym),
                "name_jp": t.info.get("longName", sym),
                "cap": "Custom",
                "sector": t.info.get("sector", "Custom Equity")
            }

        return jsonify({
            "success": True,
            "meta": meta,
            "interval": interval,
            "candles": candles,
            "prediction": pred,
            "pivots": pivots
        })

    except Exception as e:
        logger.error(f"Error fetching stock detail for {sym}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
