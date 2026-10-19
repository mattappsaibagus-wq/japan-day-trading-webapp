"""
Walk-forward intraday backtest + probability calibration for the signal engine.

  python backtest.py                       # whole universe, 15m bars, last 60 days
  python backtest.py --symbols 7203 6920   # selected codes
  python backtest.py --interval 5m --horizon 6

Rules (deliberately conservative):
  - Signal is computed on the close of bar i using only bars <= i.
  - Entry at the OPEN of bar i+1 plus slippage; no entries after 15:00 JST.
  - Bracket = engine stop / target1. If a bar touches both, the stop is assumed hit first.
  - Every position is closed at the last bar of the session (no overnight risk).
  - One position per symbol at a time. Macro agent is inactive (no point-in-time macro history).

Writes calibration.json: for each score bucket, the observed frequency that price was
higher `horizon` bars later within the same session. The live app shows that number
instead of an invented "probability". Agent weights are hand-set, not fitted to this
data — if you start tuning weights on these results, keep a held-out period or the
numbers will flatter you.
"""

import argparse
import json
import math
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd

from agents import default_fusion
from market_rules import JST, tick_size
from quant_engine import CALIBRATION_PATH, MIN_BARS, build_brackets, build_features, calculate_indicators

BUCKET_EDGES = [-100, -45, -30, -18, -5, 5, 18, 30, 45, 100.01]
LAST_ENTRY = dtime(15, 0)


def score_frame(calc, meta=None):
    fusion = default_fusion()
    scores = np.full(len(calc), np.nan)
    actions = np.array(["HOLD"] * len(calc), dtype=object)
    feats = [None] * len(calc)
    for i in range(MIN_BARS, len(calc)):
        f = build_features(calc, i, None, meta)
        r = fusion.run_all(f)
        scores[i], actions[i], feats[i] = r["final_score"], r["final_action"], f
    return scores, actions, feats


def simulate(calc, actions, feats, meta=None, slippage_ticks=1, commission_pct=0.0):
    topix500 = (meta or {}).get("topix500", False)
    sessions = calc["Session"].values
    o, h, l, c = (calc[k].values for k in ("Open", "High", "Low", "Close"))
    times = calc.index
    trades = []
    i, n = MIN_BARS, len(calc)
    while i < n - 1:
        act = actions[i]
        if act == "HOLD" or sessions[i + 1] != sessions[i] or times[i].time() >= LAST_ENTRY:
            i += 1
            continue
        br = build_brackets(act, feats[i], topix500)
        if br is None:
            i += 1
            continue
        sign = 1 if act == "BUY" else -1
        slip = slippage_ticks * tick_size(o[i + 1], topix500)
        entry = o[i + 1] + sign * slip
        risk = br["risk_per_share"]
        stop, target = br["stop_loss"], br["target1"]
        # Gap through the stop on the entry bar's open: skip, the setup is invalid
        if (sign == 1 and entry <= stop) or (sign == -1 and entry >= stop):
            i += 1
            continue

        exit_px, reason, j = None, "session_close", i + 1
        while j < n and sessions[j] == sessions[i]:
            hit_stop = l[j] <= stop if sign == 1 else h[j] >= stop
            hit_tgt = h[j] >= target if sign == 1 else l[j] <= target
            if hit_stop:
                exit_px, reason = stop - sign * slip, "stop"
                break
            if hit_tgt:
                exit_px, reason = target, "target"
                break
            if j + 1 >= n or sessions[j + 1] != sessions[i]:
                exit_px = c[j] - sign * slip
                break
            j += 1
        if exit_px is None:  # data ended mid-session
            exit_px, j = c[n - 1] - sign * slip, n - 1

        gross = sign * (exit_px - entry)
        costs = (entry + exit_px) * commission_pct / 100
        net = gross - costs
        trades.append({
            "symbol": (meta or {}).get("symbol", "?"),
            "side": act, "entry_time": times[i + 1].isoformat(), "exit_time": times[j].isoformat(),
            "entry": round(entry, 1), "exit": round(exit_px, 1), "reason": reason,
            "ret_pct": net / entry * 100, "r": net / risk if risk > 0 else 0.0,
        })
        i = j + 1
    return trades


def forward_returns(calc, horizon):
    c = calc["Close"]
    fwd = c.shift(-horizon) / c - 1
    same = calc["Session"].shift(-horizon) == calc["Session"]
    return fwd.where(same)


def summarize(trades):
    if not trades:
        return {"trades": 0}
    r = np.array([t["r"] for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    equity = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(equity) - equity)) if len(equity) else 0.0
    return {
        "trades": len(r),
        "win_rate": round(len(wins) / len(r) * 100, 1),
        "avg_win_r": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_r": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy_r": round(float(r.mean()), 3),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else math.inf,
        "total_r": round(float(r.sum()), 1),
        "max_drawdown_r": round(dd, 1),
    }


def calibrate(score_fwd_pairs, horizon, interval, meta_info):
    df = pd.DataFrame(score_fwd_pairs, columns=["score", "fwd"]).dropna()
    df = df[df["fwd"] != 0]  # unchanged price says nothing about direction
    buckets = []
    for lo, hi in zip(BUCKET_EDGES[:-1], BUCKET_EDGES[1:]):
        sub = df[(df["score"] >= lo) & (df["score"] < hi)]
        buckets.append({
            "lo": lo, "hi": round(hi), "n": int(len(sub)),
            "p_up": round(float((sub["fwd"] > 0).mean()), 4) if len(sub) else None,
            "avg_ret_pct": round(float(sub["fwd"].mean() * 100), 4) if len(sub) else None,
        })
    return {"horizon_bars": horizon, "min_samples": 50, "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
            "base_rate_up": round(float((df["fwd"] > 0).mean()), 4) if len(df) else None,
            "buckets": buckets, **meta_info}


def run_backtest(frames, metas, interval="15m", horizon=4, slippage_ticks=1, commission_pct=0.0):
    """frames: {symbol: OHLCV DataFrame}; metas: {symbol: universe entry}. Returns (report, calibration)."""
    all_trades, pairs, per_symbol = [], [], {}
    for sym, df in frames.items():
        calc = calculate_indicators(df, intraday=True)
        if calc is None or len(calc) <= MIN_BARS + horizon:
            continue
        meta = dict(metas.get(sym, {}), symbol=sym)
        scores, actions, feats = score_frame(calc, meta)
        trades = simulate(calc, actions, feats, meta, slippage_ticks, commission_pct)
        per_symbol[sym] = summarize(trades)
        all_trades.extend(trades)
        pairs.extend(zip(scores, forward_returns(calc, horizon).values))

    report = {
        "overall": summarize(all_trades),
        "by_side": {s: summarize([t for t in all_trades if t["side"] == s]) for s in ("BUY", "SELL")},
        "by_symbol": per_symbol,
        "exit_reasons": pd.Series([t["reason"] for t in all_trades]).value_counts().to_dict() if all_trades else {},
    }
    calibration = calibrate(pairs, horizon, interval, {"symbols": len(per_symbol), "interval": interval})
    return report, calibration, all_trades


def _print_report(report, calibration):
    o = report["overall"]
    print("\n=== Backtest (net of slippage/commission, R = multiples of initial risk) ===")
    for k, v in o.items():
        print(f"  {k:>16}: {v}")
    for side, s in report["by_side"].items():
        print(f"  {side:>4}: {s}")
    print(f"  exit reasons: {report['exit_reasons']}")
    print(f"\n=== Calibration: P(up after {calibration['horizon_bars']} bars) by score bucket "
          f"(base rate {calibration['base_rate_up']}) ===")
    for b in calibration["buckets"]:
        p = f"{b['p_up']:.3f}" if b["p_up"] is not None else "  -  "
        flag = "" if b["n"] >= calibration["min_samples"] else "  (too few samples — app shows 'uncalibrated')"
        print(f"  score [{b['lo']:>4}, {b['hi']:>4}): n={b['n']:>6}  p_up={p}{flag}")
    if o.get("trades", 0) and o["expectancy_r"] <= 0:
        print("\n  !! Negative expectancy: the signals as configured lose money after costs on this sample.")


def main():
    from data_provider import get_provider
    from universe import STOCKS_UNIVERSE

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="*", help="TSE codes (default: whole universe)")
    ap.add_argument("--interval", default="15m", choices=["5m", "15m"])
    ap.add_argument("--period", default="60d")
    ap.add_argument("--horizon", type=int, default=4, help="bars ahead for probability calibration")
    ap.add_argument("--slippage-ticks", type=int, default=1)
    ap.add_argument("--commission-pct", type=float, default=0.0, help="per side, e.g. 0.05")
    ap.add_argument("--no-write", action="store_true", help="don't update calibration.json")
    ap.add_argument("--trades-csv", help="write every trade to this CSV")
    args = ap.parse_args()

    metas = {s["symbol"]: s for s in STOCKS_UNIVERSE}
    syms = [c if c.endswith(".T") else f"{c}.T" for c in args.symbols] if args.symbols else list(metas)
    print(f"Downloading {len(syms)} symbols ({args.interval}, {args.period})...")
    frames = get_provider().history_batch(syms, interval=args.interval, period=args.period)

    report, calibration, trades = run_backtest(frames, metas, args.interval, args.horizon,
                                               args.slippage_ticks, args.commission_pct)
    _print_report(report, calibration)

    if args.trades_csv and trades:
        pd.DataFrame(trades).to_csv(args.trades_csv, index=False)
        print(f"\nTrades written to {args.trades_csv}")
    if not args.no_write:
        try:
            with open(CALIBRATION_PATH, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, ValueError):
            existing = {}
        existing[args.interval] = calibration
        with open(CALIBRATION_PATH, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)
        print(f"\nCalibration for {args.interval} written to {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
