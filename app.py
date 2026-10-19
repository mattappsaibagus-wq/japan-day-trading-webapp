"""
Flask Backend for Japan Day Trading Terminal
Serves market data, intraday indicators, agent signals, tick-rounded brackets and position sizing.
"""

import logging
import os
import re
import time
from datetime import datetime

import numpy as np
from flask import Flask, render_template, jsonify, request

from universe import STOCKS_UNIVERSE, MACRO_ASSETS
from quant_engine import calculate_indicators, generate_directional_prediction, calculate_pivot_points
from market_rules import JST, position_size, session_status
from data_provider import get_provider
import kronos_feed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("japan-trading-app")

app = Flask(__name__)
provider = get_provider()

CACHE = {
    "macro": {"timestamp": 0, "data": None},
    "screener": {"timestamp": 0, "data": None},
    "kronos": {"timestamp": 0, "data": None},
}
CACHE_TTL_MACRO = 60
CACHE_TTL_SCREENER = 60

SCREENER_INTERVAL = "15m"
INTRADAY_PERIOD = "30d"   # ~600 bars of 15m: enough EMA50 warm-up and 10-session RVol baseline
CHART_SESSIONS = 5
JST_OFFSET_SEC = 9 * 3600  # lightweight-charts renders epoch seconds as UTC; shift so axis reads JST

SYMBOL_RE = re.compile(r"^[0-9A-Z]{4}(\.T)?$")
UNIVERSE_BY_SYMBOL = {s["symbol"]: s for s in STOCKS_UNIVERSE}


def _pct_change(series):
    s = series.dropna()
    if len(s) < 2:
        return None
    curr, prev = float(s.iloc[-1]), float(s.iloc[-2])
    return {"price": curr, "change": curr - prev, "change_pct": (curr - prev) / prev * 100}


def get_macro_context():
    now = time.time()
    if CACHE["macro"]["data"] and now - CACHE["macro"]["timestamp"] < CACHE_TTL_MACRO:
        return CACHE["macro"]["data"]

    try:
        frames = provider.history_batch([m["symbol"] for m in MACRO_ASSETS.values()], interval="1d", period="5d")
        macro = {"as_of": datetime.now(JST).isoformat(timespec="seconds")}
        for key, nd in (("nikkei", 2), ("usdjpy", 3)):
            sym = MACRO_ASSETS[key]["symbol"]
            chg = _pct_change(frames[sym]["Close"]) if sym in frames else None
            if chg:
                macro[key] = {"price": round(chg["price"], nd), "change": round(chg["change"], nd),
                              "change_pct": round(chg["change_pct"], 2)}
                macro[f"{key}_change_pct"] = chg["change_pct"]
        if "nikkei" not in macro:
            raise RuntimeError("Nikkei 225 data unavailable")

        nk = macro.get("nikkei_change_pct", 0)
        fx = macro.get("usdjpy_change_pct", 0)
        if nk > 0.5 and fx > 0.2:
            macro["regime"], macro["bias"] = "Risk-On (Export Tailwind)", "BULLISH"
        elif nk > 0.2:
            macro["regime"], macro["bias"] = "Mildly Bullish", "BULLISH"
        elif nk < -0.5:
            macro["regime"], macro["bias"] = "Risk-Off (Caution / Selective Shorts)", "BEARISH"
        else:
            macro["regime"], macro["bias"] = "Neutral / Range-Bound", "NEUTRAL"
        CACHE["macro"] = {"timestamp": now, "data": macro}
    except Exception as e:
        logger.error(f"Error fetching macro: {e}")
        if CACHE["macro"]["data"]:
            # Serve the last real values, clearly marked stale — never invented numbers
            stale = dict(CACHE["macro"]["data"], stale=True)
            return stale
        return {"error": "macro data unavailable", "stale": True}

    return CACHE["macro"]["data"]


def format_ticker_symbol(code_or_symbol):
    code = code_or_symbol.strip().upper()
    if not code.endswith(".T"):
        code = f"{code}.T"
    return code


def data_status():
    return {"provider": provider.name, "realtime": provider.realtime,
            "delay_minutes": provider.delay_minutes}


@app.route("/")
def index():
    return render_template("index.html", stocks=STOCKS_UNIVERSE)


@app.route("/api/macro")
def api_macro():
    return jsonify(get_macro_context())


@app.route("/api/session")
def api_session():
    return jsonify(dict(session_status(), data=data_status()))


def _analyze_screener():
    macro = get_macro_context()
    symbols = [s["symbol"] for s in STOCKS_UNIVERSE]
    try:
        frames = provider.history_batch(symbols, interval=SCREENER_INTERVAL, period=INTRADAY_PERIOD)
    except Exception as e:
        logger.error(f"Batch fetch error: {e}")
        frames = {}

    results = []
    for meta in STOCKS_UNIVERSE:
        sym = meta["symbol"]
        try:
            df = frames.get(sym)
            calc = calculate_indicators(df, intraday=True) if df is not None else None
            if calc is None:
                continue
            pred = generate_directional_prediction(calc, macro, meta, SCREENER_INTERVAL)
            ind, lv = pred["indicators"], pred["levels"]
            price = ind["close"]
            prev_close = lv["prev_day_close"]
            chg = price - prev_close if prev_close else 0.0
            vwap_dev = ((price - lv["vwap"]) / lv["vwap"] * 100) if lv["vwap"] else None
            gap = ((lv["session_open"] - prev_close) / prev_close * 100) if prev_close and lv["session_open"] else None
            results.append({
                **{k: meta[k] for k in ("symbol", "code", "name", "name_jp", "cap", "sector")},
                "price": price,
                "change": round(chg, 1),
                "change_pct": round(chg / prev_close * 100, 2) if prev_close else 0.0,
                "gap_pct": round(gap, 2) if gap is not None else None,
                "vwap_dev_pct": round(vwap_dev, 2) if vwap_dev is not None else None,
                "rvol": ind["rvol"],
                "rsi": ind["rsi"],
                "score": pred["score"],
                "signal": pred["signal"],
                "signal_jp": pred["signal_jp"],
                "mark": pred["mark"],
                "action": pred["action"],
                "action_jp": pred["action_jp"],
                "action_en": pred["action_en"],
                "prob_up": pred["probability_up"],
                "prob_down": pred["probability_down"],
                "prob_signal": pred["probability_signal"],
                "edge_pp": pred["signal_edge_pp"],
                "setup": pred["setup"],
                "near_limit": any("ストップ" in w for w in pred["warnings"]),
                "last_bar": calc.index[-1].isoformat(),
            })
        except Exception as ex:
            logger.warning(f"Error analyzing {sym}: {ex}")

    results.sort(key=lambda x: abs(x["score"]), reverse=True)
    return results


@app.route("/api/screener")
def api_screener():
    now = time.time()
    if CACHE["screener"]["data"] is not None and now - CACHE["screener"]["timestamp"] < CACHE_TTL_SCREENER:
        data = CACHE["screener"]["data"]
    else:
        data = _analyze_screener()
        CACHE["screener"] = {"timestamp": now, "data": data}

    cap_filter = request.args.get("cap", "all").lower()
    if cap_filter != "all":
        data = [d for d in data if d["cap"].lower() == cap_filter]
    action_filter = request.args.get("action", "all").upper()
    if action_filter != "ALL":
        data = [d for d in data if d["action_en"] == action_filter]

    return jsonify({"stocks": data, "count": len(data), "interval": SCREENER_INTERVAL,
                    "data": data_status()})


def _chart_payload(calc, intraday):
    if intraday:
        sessions = calc["Session"].unique()[-CHART_SESSIONS:]
        calc = calc[calc["Session"].isin(sessions)]
    else:
        calc = calc.iloc[-120:]
    offset = JST_OFFSET_SEC if intraday else 0
    candles, vwap = [], []
    for idx, row in calc.iterrows():
        ts = int(idx.timestamp()) + offset
        candles.append({"time": ts, "open": round(float(row["Open"]), 1), "high": round(float(row["High"]), 1),
                        "low": round(float(row["Low"]), 1), "close": round(float(row["Close"]), 1),
                        "volume": int(row["Volume"])})
        if intraday and np.isfinite(row["VWAP"]):
            vwap.append({"time": ts, "value": round(float(row["VWAP"]), 2),
                         "session": str(row["Session"])})
    return candles, vwap


@app.route("/api/stock/<symbol>")
def api_stock_detail(symbol):
    sym = format_ticker_symbol(symbol)
    if not SYMBOL_RE.match(sym):
        return jsonify({"success": False, "error": "Invalid TSE code (expected 4 characters, e.g. 7203)"}), 400

    interval = request.args.get("interval", "15m")
    if interval not in ("5m", "15m", "1d"):
        return jsonify({"success": False, "error": "interval must be 5m, 15m or 1d"}), 400
    intraday = interval != "1d"
    period = INTRADAY_PERIOD if intraday else "1y"

    macro = get_macro_context()
    meta = UNIVERSE_BY_SYMBOL.get(sym)
    try:
        df = provider.history(sym, interval=interval, period=period)
        if len(df) == 0:
            return jsonify({"success": False, "error": f"No data for {sym}"}), 404
        if meta is None:
            info = provider.info(sym)
            meta = {"symbol": sym, "code": sym.replace(".T", ""),
                    "name": info.get("shortName", sym), "name_jp": info.get("longName", sym),
                    "cap": "Custom", "sector": info.get("sector", "Custom Equity"),
                    # Unknown membership: standard (coarser) tick table is the safe default
                    "topix500": False, "fx_beta": 0.0}

        calc = calculate_indicators(df, intraday=intraday)
        if calc is None:
            return jsonify({"success": False, "error": "Not enough bars to analyse"}), 422
        pred = generate_directional_prediction(calc, macro, meta, interval)
        lv = pred["levels"]
        pivots = None
        if lv["prev_day_high"] and lv["prev_day_low"] and lv["prev_day_close"]:
            pivots = calculate_pivot_points(lv["prev_day_high"], lv["prev_day_low"], lv["prev_day_close"],
                                            meta.get("topix500", False))
        candles, vwap = _chart_payload(calc, intraday)

        return jsonify({
            "success": True,
            "meta": meta,
            "interval": interval,
            "candles": candles,
            "vwap": vwap,
            "prediction": pred,
            "pivots": pivots,
            "last_bar": calc.index[-1].isoformat(),
            "data": data_status(),
        })
    except Exception as e:
        logger.exception(f"Error fetching stock detail for {sym}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/kronos")
def api_kronos():
    """Kronos next-hour forecasts from this repo's Kronos job (it refreshes every 30 min in TSE hours)."""
    c = CACHE["kronos"]
    if c["data"] is None or time.time() - c["timestamp"] > 1800:
        c["data"], c["timestamp"] = kronos_feed.fetch(), time.time()
    return jsonify(c["data"])


@app.route("/api/position-size")
def api_position_size():
    try:
        args = {k: float(request.args[k]) for k in ("account", "risk_pct", "entry", "stop")}
    except (KeyError, ValueError):
        return jsonify({"error": "account, risk_pct, entry and stop are required numbers"}), 400
    max_cap = float(request.args.get("max_capital_pct", 100))
    return jsonify(position_size(args["account"], args["risk_pct"], args["entry"], args["stop"],
                                 max_capital_pct=max_cap))


if __name__ == "__main__":
    # Bind to localhost and keep the Werkzeug debugger off unless explicitly requested:
    # the debugger allows arbitrary code execution if the port is reachable.
    app.run(host=os.environ.get("KABU_HOST", "127.0.0.1"),
            port=int(os.environ.get("KABU_PORT", 5000)),
            debug=os.environ.get("KABU_DEBUG") == "1")
