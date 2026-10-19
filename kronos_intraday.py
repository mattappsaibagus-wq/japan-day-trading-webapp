"""
Kronos intraday forecasts: where price goes over the next hour of today's session.

Kronos (https://github.com/shiyu-coder/Kronos, MIT) is a candlestick foundation
model. This module runs it on the same 15-minute bars the screener uses and
forecasts the next 4 bars (one hour of trading, the same horizon the agents are
backtested on). It samples several independent paths per symbol so the output
says how often they agree, not only the average.

It needs PyTorch, the Kronos repo on disk (KRONOS_DIR) and the Hugging Face
weights, so it runs in GitHub Actions (.github/workflows/kronos.yml), not in the
web app. The web app reads the JSON it writes through kronos_feed.py.

    python kronos_intraday.py out.json [--limit N]
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from market_rules import JST, next_trading_day

MODEL_ID = "NeoQuasar/Kronos-small"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
SOURCE = "Kronos (shiyu-coder/Kronos, NeoQuasar/Kronos-small)"
INTERVAL = "15m"
BAR_MIN = 15
HORIZON_BARS = 4          # 1 hour ahead
LOOKBACK = 400            # ~18 sessions of 15m bars
MIN_HISTORY = 200
N_PATHS = 8
MAX_CONTEXT = 512
FEED_DELAY_MIN = 20       # Yahoo TSE delay: a bar is only complete this long after it ends
MIN_AGREEMENT = 0.625     # below this the paths disagree: reported as flat

# 15m bar start times of a TSE session (morning 9:00-11:30, afternoon 12:30-15:30)
SESSION_SLOTS = [(h, m) for h in range(9, 16) for m in (0, 15, 30, 45)
                 if (9, 0) <= (h, m) <= (11, 15) or (12, 30) <= (h, m) <= (15, 15)]


def future_bar_times(last_bar, count=HORIZON_BARS):
    """The next `count` 15m bar start times after last_bar (naive JST), skipping lunch, nights and holidays."""
    out, d = [], last_bar.date()
    later = [s for s in SESSION_SLOTS if s > (last_bar.hour, last_bar.minute)]
    while len(out) < count:
        for h, m in later:
            out.append(datetime(d.year, d.month, d.day, h, m))
            if len(out) == count:
                break
        d = next_trading_day(d)
        later = SESSION_SLOTS
    return out


def prepare(hist, now_jst):
    """15m OHLCV DataFrame -> (context DataFrame with naive JST index, reason or None)."""
    if hist is None or len(hist) == 0:
        return None, "no_history"
    df = hist.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].astype(float)
    df["volume"] = df["volume"].fillna(0.0)
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Tokyo").tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # Drop a bar that is still forming (Yahoo returns the in-progress bar).
    now_naive = now_jst.astimezone(JST).replace(tzinfo=None)
    cutoff = now_naive - timedelta(minutes=BAR_MIN + FEED_DELAY_MIN)
    df = df[df.index <= cutoff]
    if len(df) < MIN_HISTORY:
        return None, "short_history"
    return df.tail(LOOKBACK), None


def load_predictor(kronos_dir=None):
    """Load Kronos from a local checkout of github.com/shiyu-coder/Kronos."""
    import torch
    kronos_dir = kronos_dir or os.environ.get("KRONOS_DIR", "Kronos")
    if kronos_dir not in sys.path:
        sys.path.insert(0, kronos_dir)
    from model import Kronos, KronosTokenizer, KronosPredictor

    torch.set_num_threads(max(1, os.cpu_count() or 1))
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
    model = Kronos.from_pretrained(MODEL_ID)
    tokenizer.eval()
    model.eval()
    return KronosPredictor(model, tokenizer, max_context=MAX_CONTEXT)


def sample_paths(predictor, prepared, n_paths=N_PATHS, chunk=64):
    """{symbol: (df, future_times)} -> {symbol: array(n_paths, HORIZON_BARS) of closes}.

    Every path is its own batch row: Kronos' sample_count averages paths
    internally, which would hide how much they disagree.
    """
    groups = {}
    for sym, (df, _) in prepared.items():
        groups.setdefault(len(df), []).append(sym)   # predict_batch needs equal lengths
    out = {}
    for syms in groups.values():
        rows = [s for s in syms for _ in range(n_paths)]
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            preds = predictor.predict_batch(
                df_list=[prepared[s][0] for s in part],
                x_timestamp_list=[pd.Series(prepared[s][0].index) for s in part],
                y_timestamp_list=[pd.Series(pd.DatetimeIndex(prepared[s][1])) for s in part],
                pred_len=HORIZON_BARS, T=1.0, top_p=0.9, sample_count=1, verbose=False,
            )
            for s, p in zip(part, preds):
                out.setdefault(s, []).append(p["close"].to_numpy(dtype=float))
    return {s: np.vstack(v) for s, v in out.items() if len(v) == n_paths}


def summarize(last_close, closes):
    """Paths of closes -> forecast for the bar HORIZON_BARS ahead."""
    rets = (closes[:, -1] - last_close) / last_close * 100.0
    mean = float(np.mean(rets))
    agreement = float(np.mean(np.sign(rets) == np.sign(mean))) if mean else 0.0
    direction = ("up" if mean > 0 else "down") if agreement >= MIN_AGREEMENT else "flat"
    return {
        "direction": direction,
        "expected_move_pct": round(mean, 3),
        "range_pct": [round(float(np.min(rets)), 3), round(float(np.max(rets)), 3)],
        "path_agreement": round(agreement, 3),
    }


def run(frames, predictor, now=None):
    """frames: {symbol: 15m OHLCV DataFrame} -> feed dict (the format kronos_feed serves)."""
    now_jst = (now or datetime.now(JST)).astimezone(JST)
    prepared, skipped = {}, {}
    for sym, hist in frames.items():
        df, why = prepare(hist, now_jst)
        if df is None:
            skipped[why] = skipped.get(why, 0) + 1
        else:
            prepared[sym] = (df, future_bar_times(df.index[-1].to_pydatetime()))
    t0 = time.time()
    paths = sample_paths(predictor, prepared) if prepared else {}
    forecasts = {}
    for sym, closes in paths.items():
        df, fut = prepared[sym]
        fc = summarize(float(df["close"].iloc[-1]), closes)
        fc.update({
            "last_bar": df.index[-1].strftime("%Y-%m-%dT%H:%M:00+09:00"),
            "target_bar": fut[-1].strftime("%Y-%m-%dT%H:%M:00+09:00"),
            "model": MODEL_ID,
        })
        if np.isfinite(fc["expected_move_pct"]):
            forecasts[sym] = fc
    return {
        "generated_at": now_jst.isoformat(timespec="seconds"),
        "source": SOURCE,
        "interval": INTERVAL,
        "horizon_bars": HORIZON_BARS,
        "n_paths": N_PATHS,
        "forecasts": forecasts,
        "stats": {"symbols": len(frames), "forecast": len(forecasts), "skipped": skipped,
                  "seconds": round(time.time() - t0, 1)},
    }


def main(argv):
    out = argv[0] if argv else "kronos.json"
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    from data_provider import get_provider
    from universe import STOCKS_UNIVERSE

    symbols = [s["symbol"] for s in STOCKS_UNIVERSE][:limit]
    frames = get_provider().history_batch(symbols, interval=INTERVAL, period="30d")
    seed = int(datetime.now(JST).strftime("%Y%m%d%H"))
    np.random.seed(seed)
    import torch
    torch.manual_seed(seed)
    feed = run(frames, load_predictor())
    with open(out, "w") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    print(json.dumps(feed["stats"]))
    for sym, fc in sorted(feed["forecasts"].items()):
        print(sym, fc["direction"], fc["expected_move_pct"], fc["path_agreement"], fc["target_bar"])
    if not feed["forecasts"]:
        sys.exit("no forecasts produced")


if __name__ == "__main__":
    main(sys.argv[1:])
