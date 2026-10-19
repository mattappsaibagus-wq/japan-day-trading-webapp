from agents.base import Agent, valid


class VWAPAgent(Agent):
    """Position vs. session VWAP and its standard-deviation bands (intraday only)."""
    key = "vwap"
    label = "VWAP (session)"

    def score(self, f):
        close, vwap, sd = f["close"], f.get("vwap"), f.get("vwap_sd")
        if not f.get("intraday") or not valid(close, vwap, sd):
            return None, ["VWAP n/a on daily bars"]
        if sd <= 0:
            return (20.0 if close > vwap else -20.0 if close < vwap else 0.0), []
        z = (close - vwap) / sd
        reasons = [f"{z:+.1f}σ from VWAP"]
        # Holding above VWAP is bullish, but beyond +2σ the move is stretched; mirror below
        if abs(z) <= 2:
            s = z * 30
        else:
            s = (60 - (abs(z) - 2) * 40) * (1 if z > 0 else -1)
            reasons.append("stretched beyond 2σ — mean-reversion risk")
        return s, reasons
