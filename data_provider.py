"""
Market data access. All price fetching goes through a provider object so the
Yahoo Finance source can be swapped for a real-time feed (kabu STATION API,
Rakuten RSS, J-Quants minute bars, ...) by implementing the same three methods.

Yahoo Finance TSE data is delayed ~20 minutes and unofficial: fine for
research and backtesting, not for live intraday execution.
"""

import logging
import os

import pandas as pd

logger = logging.getLogger("japan-trading-app.data")

# Yahoo intraday history limits
MAX_PERIOD = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "60m": "730d", "1d": "max"}


class YahooProvider:
    name = "yahoo"
    delay_minutes = 20
    realtime = False

    def __init__(self):
        import yfinance as yf  # imported lazily so tests don't need network libraries
        self.yf = yf

    def history(self, symbol, interval="15m", period="30d"):
        df = self.yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        return _clean(df)

    def history_batch(self, symbols, interval="15m", period="30d"):
        """Returns {symbol: DataFrame}. Missing symbols are omitted."""
        raw = self.yf.download(symbols, period=period, interval=interval, progress=False,
                               group_by="ticker", auto_adjust=False, threads=True)
        out = {}
        for sym in symbols:
            try:
                df = raw[sym] if len(symbols) > 1 else raw
            except KeyError:
                continue
            df = _clean(df)
            if len(df):
                out[sym] = df
        return out

    def info(self, symbol):
        try:
            return self.yf.Ticker(symbol).info or {}
        except Exception as e:  # Yahoo's info endpoint is flaky; metadata is optional
            logger.warning(f"info lookup failed for {symbol}: {e}")
            return {}


INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


def complete_bars(df, interval, delay_minutes=0, now=None):
    """Drop intraday bars that are still forming.

    Yahoo returns the current, partial bar. Signals and the backtest must see the
    same thing, and the backtest only ever sees finished bars, so a bar is kept
    only once it has ended and the feed delay has passed.
    """
    minutes = INTERVAL_MINUTES.get(interval)
    if df is None or len(df) == 0 or minutes is None:
        return df
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="Asia/Tokyo")
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("Asia/Tokyo")
    if now.tzinfo is None:
        now = now.tz_localize("Asia/Tokyo")
    ends = idx + pd.Timedelta(minutes=minutes + delay_minutes)
    return df[ends <= now]


def _clean(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    return df.dropna(subset=["Close"])


_PROVIDERS = {"yahoo": YahooProvider}


def get_provider():
    name = os.environ.get("KABU_DATA_PROVIDER", "yahoo").lower()
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown data provider '{name}'. Available: {', '.join(_PROVIDERS)}")
    return _PROVIDERS[name]()
