# Kabutrader — Japan Day Trading & Predictive Terminal
**東京デイトレード・ターミナル**

A quantitative day trading terminal and market screener specialized for the Tokyo Stock Exchange (TSE / 東証), covering Large-Cap, Mid-Cap, and Small-Cap/Growth Japanese equities.

---

## Features

- **Categorized TSE Universe**:
  - **Large-Cap**: Core Prime leaders (Toyota `7203.T`, Sony `6758.T`, Fast Retailing `9983.T`, Tokyo Electron `8035.T`, SoftBank Group `9984.T`, Honda `7267.T`, Hitachi `6501.T`, Keyence `6861.T`, MUFG `8306.T`).
  - **Mid-Cap**: High-beta momentum favorites (Lasertec `6920.T`, Advantest `6857.T`, Socionext `6526.T`, Disco `6146.T`, Mercari `4385.T`, Rakuten `4755.T`, Renesas `6723.T`, Kawasaki Heavy `7012.T`).
  - **Small-Cap & Growth**: TSE Growth movers (ANYCOLOR `5032.T`, COVER `5253.T`, Appier `4180.T`, Bank of Innovation `4393.T`, GENDA `9166.T`, freee `4478.T`, Sansan `4443.T`, ispace `9348.T`, BASE `4477.T`, FRONTEO `2158.T`).
  - **Custom Code Search**: Enter any 4-digit TSE ticker (e.g., `7203` or `6920`) to scan on demand.

- **Intraday Signal Engine** (computed on 5m / 15m bars, not daily bars):
  - **Trend**: EMA 9/21/50 stack and EMA21 slope.
  - **Momentum**: Wilder RSI(14) regime + MACD cross / histogram acceleration.
  - **Breakout**: opening-range (first 30 min) and prior-day high/low breaks, Bollinger squeeze release, gated by relative volume.
  - **VWAP**: position vs. session VWAP (resets every morning) and its ±1σ/±2σ bands.
  - **Macro**: Nikkei 225 + USD/JPY, scaled per stock by FX sensitivity (exporters vs. domestic).
  - Agent weights are hand-set and every agent explains its score in the UI.
  - **Probability is measured, not invented**: the "上昇確率" column stays *未検証 (uncalibrated)* until you run `backtest.py`, which records how often price actually rose after each score bucket.

- **Day-Trader Execution & Risk**:
  - ATR stop (1.2× intraday ATR) and 1.5R / 2.6R targets, **rounded to the TSE tick table** (呼値, TOPIX500 vs. standard) and clipped to the daily price limits.
  - **Price limits (ストップ高/ストップ安)** shown per stock, with warnings when price is within 2 ATR.
  - **Position sizing**: account size × risk % ÷ stop distance, in 100-share units (単元株), capped by capital.
  - Intraday levels: VWAP bands, opening range, prior-day high/low/close, floor pivots.
  - No brackets are shown for HOLD signals.

- **Market Session**: JPX holiday calendar (national holidays + Dec 31–Jan 3), pre-open, morning/afternoon session, lunch break, closing auction (15:25–15:30).

- **Backtest** (`backtest.py`): walk-forward replay of the same engine with next-bar entries, slippage, optional commission, stop-first assumption when a bar hits both levels, and forced flat at the close (no overnight positions). Reports win rate, expectancy (R), profit factor and drawdown.

- **Terminal Interface**:
  - Live JST clock and TSE session status; data-feed delay badge.
  - Candlestick chart (JST axis) with session VWAP and entry/stop/target lines.
  - Cap-tier and signal filtering; gap %, VWAP deviation and time-of-day RVol in the scanner.

## Limitations — read before trading

- **Data is Yahoo Finance, delayed ~20 minutes** and unofficial. Fine for research and backtests; not for live entries. `data_provider.py` is the single place to plug in a real-time feed (kabu STATION API, Rakuten RSS, J-Quants minute bars).
- No order-book (板) or tape (歩み値), no short-borrow availability (貸借/逆日歩), no TDnet/earnings alerts, no order execution.
- TOPIX500 membership (tick table) is set by hand in `universe.py` and changes every October.
- A positive backtest on 60 days of data is not proof of an edge. If you tune agent weights on backtest results, keep a held-out period.

---

## Project Structure

```
japan-day-trading-webapp/
├── app.py             # Flask backend & REST API endpoints
├── quant_engine.py    # Intraday indicators, agent fusion, tick-rounded brackets
├── agents/            # Trend / Momentum / Breakout / VWAP / Macro scoring agents
├── market_rules.py    # Tick sizes, price limits, position sizing, JPX calendar
├── data_provider.py   # Market data source (Yahoo; swap for a real-time feed)
├── backtest.py        # Walk-forward backtest + probability calibration
├── tests/             # pytest suite (synthetic data, no network needed)
├── universe.py        # Stock catalog across Large, Mid, and Small caps
├── run.sh             # Executable launcher script
├── preview.html       # Standalone chat/widget preview
├── templates/
│   └── index.html     # Terminal HTML structure
└── static/
    ├── css/style.css  # Dark terminal theme
    └── js/app.js      # Real-time UI logic & chart rendering
```

---

## Quick Start

```bash
./run.sh                      # creates .venv, installs requirements, serves http://127.0.0.1:5000
```

Calibrate the probabilities (needs internet access to Yahoo Finance):

```bash
.venv/bin/python backtest.py                 # whole universe, 15m bars, last 60 days
.venv/bin/python backtest.py --interval 5m --horizon 6 --commission-pct 0.05
```

Run tests:

```bash
.venv/bin/python -m pytest
```

Environment variables: `KABU_HOST` (default `127.0.0.1`), `KABU_PORT` (5000), `KABU_DEBUG=1` to enable the Flask debugger (never on a reachable network), `KABU_DATA_PROVIDER` (`yahoo`).
