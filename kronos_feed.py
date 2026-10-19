"""
Kronos intraday forecasts, as published by this repo's own Kronos job.

kronos_intraday.py runs the Kronos model (github.com/shiyu-coder/Kronos) in
GitHub Actions during TSE hours (.github/workflows/kronos.yml) and pushes the
result to the kronos-data branch. The web app cannot run the model itself (it
needs PyTorch and the Hugging Face weights), so it reads that file.

Forecasts are for the next hour of trading (4 x 15m bars). They are shown beside
the intraday agents and do not enter the score until they have been backtested.
"""

import json
import logging
import urllib.request

logger = logging.getLogger("japan-trading-app")

FEED_URL = "https://raw.githubusercontent.com/mattappsaibagus-wq/japan-day-trading-webapp/kronos-data/kronos.json"


def parse(data):
    """Keep only well-formed forecasts from a kronos_intraday feed."""
    keep = ("direction", "expected_move_pct", "range_pct", "path_agreement", "last_bar", "target_bar", "model")
    forecasts = {
        sym: {k: fc.get(k) for k in keep}
        for sym, fc in (data.get("forecasts") or {}).items()
        if isinstance(fc, dict) and fc.get("direction") in ("up", "down", "flat")
    }
    return {
        "generated_at": data.get("generated_at"),
        "source": data.get("source"),
        "interval": data.get("interval"),
        "horizon_bars": data.get("horizon_bars"),
        "forecasts": forecasts,
    }


def fetch(url=FEED_URL, timeout=20):
    """Download and parse the feed. On any failure returns an empty feed with the error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return parse(json.load(r))
    except Exception as e:  # network, HTTP or JSON errors: show no Kronos rather than break the page
        logger.warning(f"Kronos feed unavailable: {e}")
        return {"generated_at": None, "source": None, "forecasts": {}, "error": str(e)}
