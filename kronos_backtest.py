"""
Walk-forward check of the Kronos next-hour forecasts on past 15m bars.

At a few fixed times on each of the last N sessions, Kronos sees only the bars up
to that time (the same context kronos_intraday.py gives it live) and forecasts the
next 4 bars. The forecast is then compared with what actually happened.

Reports, for up/down calls (flat calls are not traded):
  * hit rate: share of calls whose direction was right
  * net bps per call after 1 tick of slippage on each side (entry at the next
    bar's open, exit at the close 4 bars later), with a day-clustered t-stat

Runs in GitHub Actions (.github/workflows/kronos-backtest.yml), where PyTorch and
the weights are available.

    python kronos_backtest.py out.json [--days 15] [--paths 4]
"""

import json
import sys
import time
from datetime import time as dtime

import numpy as np
import pandas as pd

import kronos_intraday as ki
from market_rules import tick_size

CHECK_TIMES = [dtime(10, 0), dtime(11, 0), dtime(13, 30), dtime(14, 15)]  # last complete bar at these starts


def build_cases(frames, days):
    """[(symbol, context_df, future_times, entry_open, exit_close, day)]"""
    cases = []
    for sym, hist in frames.items():
        full = hist.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].astype(float)
        full.index = pd.DatetimeIndex(full.index).tz_convert("Asia/Tokyo").tz_localize(None)
        full = full[~full.index.duplicated(keep="last")].sort_index().dropna()
        sessions = sorted(set(full.index.date))[-days - 1:-1]  # skip today's partial session
        for d in sessions:
            for t in CHECK_TIMES:
                ts = pd.Timestamp.combine(d, t)
                if ts not in full.index:
                    continue
                pos = full.index.get_loc(ts)
                if pos + ki.HORIZON_BARS >= len(full) or pos + 1 < ki.MIN_HISTORY:
                    continue
                ctx = full.iloc[max(0, pos + 1 - ki.LOOKBACK):pos + 1]
                fut = full.iloc[pos + 1:pos + 1 + ki.HORIZON_BARS]
                if fut.index[-1].date() != d:  # stay within the session: no overnight holds
                    continue
                cases.append((sym, ctx, list(fut.index.to_pydatetime()),
                              float(fut["open"].iloc[0]), float(fut["close"].iloc[-1]), str(d)))
    return cases


def evaluate(cases, predictor, meta, paths, days):
    t0 = time.time()
    rows = []
    for i in range(0, len(cases), 33):
        batch = cases[i:i + 33]
        prepared = {f"{k}": (c[1], c[2]) for k, c in enumerate(batch)}
        paths_out = ki.sample_paths(predictor, prepared, n_paths=paths)
        for k, c in enumerate(batch):
            closes = paths_out.get(f"{k}")
            if closes is None:
                continue
            fc = ki.summarize(float(c[1]["close"].iloc[-1]), closes)
            sym, entry, exit_, day = c[0], c[3], c[4], c[5]
            tick = tick_size(entry, meta[sym]["topix500"])
            gross = (exit_ - entry) / entry * 1e4
            rows.append({"symbol": sym, "day": day, "cap": meta[sym]["cap"], "direction": fc["direction"],
                         "expected_move_pct": fc["expected_move_pct"], "agreement": fc["path_agreement"],
                         "gross_bps": gross, "cost_bps": 2 * tick / entry * 1e4})
        print(f"  {min(i + 33, len(cases))}/{len(cases)} ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    report = {"cases": len(df), "days": days, "paths": paths, "horizon_bars": ki.HORIZON_BARS,
              "check_times": [t.strftime("%H:%M") for t in CHECK_TIMES], "groups": {}}
    calls = df[df.direction != "flat"].copy()
    calls["sign"] = np.where(calls.direction == "up", 1, -1)
    calls["dir_bps"] = calls.sign * calls.gross_bps
    calls["net_bps"] = calls.dir_bps - calls.cost_bps
    for name, g in [("all", calls), ("large+mid", calls[calls.cap != "Small"]),
                    ("agreement>=0.75", calls[calls.agreement >= 0.75]),
                    ("large+mid, agreement>=0.75", calls[(calls.cap != "Small") & (calls.agreement >= 0.75)])]:
        if len(g) < 10:
            continue
        daily = g.groupby("day").net_bps.mean()
        t = float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))) if len(daily) > 1 and daily.std() > 0 else None
        report["groups"][name] = {
            "calls": int(len(g)), "hit_rate": round(float((g.dir_bps > 0).mean()), 3),
            "gross_bps": round(float(g.dir_bps.mean()), 2), "net_bps": round(float(g.net_bps.mean()), 2),
            "day_t": round(t, 2) if t is not None else None,
        }
    report["flat_share"] = round(float((df.direction == "flat").mean()), 3) if len(df) else None
    return report


def main(argv):
    out = argv[0] if argv else "kronos_backtest.json"
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 15
    paths = int(argv[argv.index("--paths") + 1]) if "--paths" in argv else 4
    from data_provider import get_provider
    from universe import STOCKS_UNIVERSE
    import torch

    meta = {s["symbol"]: s for s in STOCKS_UNIVERSE}
    frames = get_provider().history_batch(list(meta), interval=ki.INTERVAL, period="60d")
    cases = build_cases(frames, days)
    print(f"{len(cases)} cases over {days} sessions", flush=True)

    np.random.seed(0)
    torch.manual_seed(0)
    report = evaluate(cases, ki.load_predictor(), meta, paths, days)
    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
