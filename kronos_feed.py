"""
Kronos next-session forecasts, read from the stock-scanner (kaitoisland) pipeline.

Kronos is a candlestick foundation model that stock-scanner runs once per scan on
daily bars, in GitHub Actions. This app does not run the model itself (it needs
PyTorch and the Hugging Face weights); it reuses the forecasts that pipeline
publishes. They are daily, next-session forecasts, so they are shown beside the
intraday agents and never enter the intraday score.

stock-scanner only emits a forecast when its sample paths agree, and only for its
own watchlist, so many symbols have none.
"""

import json
import logging
import urllib.request

logger = logging.getLogger("japan-trading-app")

FEED_URL = "https://raw.githubusercontent.com/mattappsaibagus-wq/stock-scanner/main/dashboard/data.json"
SOURCE = "kaitoisland (stock-scanner)"


def parse(data):
    """Extract {symbol: forecast} from a stock-scanner data.json payload."""
    forecasts = {}
    for rec in data.get("recommendations", []):
        sym = rec.get("symbol")
        for det in rec.get("details") or []:
            fc = det.get("forecast")
            if det.get("agent") != "kronos_agent" or not sym or not fc:
                continue
            sig = (det.get("signals") or [{}])[0]
            forecasts[sym] = {
                "direction": "up" if sig.get("type") == "kronos_forecast_up" else "down",
                "expected_move_pct": fc.get("expected_move_pct"),
                "range_pct": fc.get("range_pct"),
                "path_agreement": fc.get("path_agreement"),
                "target_date": fc.get("target_date"),
                "last_bar_date": fc.get("last_bar_date"),
                "model": fc.get("model"),
            }
    return {"generated_at": data.get("generated_at"), "source": SOURCE, "forecasts": forecasts}


def fetch(url=FEED_URL, timeout=20):
    """Download and parse the feed. On any failure returns an empty feed with the error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse(json.load(r))
    except Exception as e:  # network, HTTP or JSON errors: show no Kronos rather than break the page
        logger.warning(f"Kronos feed unavailable: {e}")
        return {"generated_at": None, "source": SOURCE, "forecasts": {}, "error": str(e)}
