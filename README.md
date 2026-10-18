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

- **Multi-Factor Predictive Signal Engine**:
  - **Trend (30%)**: EMA 9, 21, and 50 alignment + VWAP position.
  - **Momentum (25%)**: Wilder RSI(14) + MACD line/signal divergence and histogram velocity.
  - **Volatility & Squeeze (20%)**: Bollinger Bands %B and squeeze detection.
  - **Institutional Volume (15%)**: Relative Volume (RVol) confirming breakout participation.
  - **Japan Macro Tailwind (10%)**: USD/JPY exchange rate direction + Nikkei 225 headline sentiment.
  - **Output**: Directional Signal (`STRONG BUY`, `BUY`, `NEUTRAL`, `SELL`, `STRONG SELL`), Win Probability % (Bullish vs. Bearish odds), and Playbook Classification.

- **Day-Trader Risk & Execution Brackets**:
  - Dynamic ATR-based Stop Loss (`1.5 * ATR(14)`).
  - Target 1 (`1.5R`) and Target 2 (`2.6R`) with automated Risk/Reward ratios.
  - Floor Pivot Points (Classic P, R1, R2, S1, S2).

- **Terminal Interface**:
  - Live JST Tokyo clock and TSE market status.
  - Interactive candlestick chart with volume bars.
  - Cap-tier filtering and real-time screener sorting.

---

## Project Structure

```
japan-day-trading-webapp/
├── app.py             # Flask backend & REST API endpoints
├── quant_engine.py    # Technical indicators, multi-factor scoring & ATR brackets
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

### 1. Launch the Server
```bash
cd /home/senseimat/japan-day-trading-webapp
./run.sh
```

### 2. Access the Webapp
Open your browser to:
```
http://127.0.0.1:5000
```
