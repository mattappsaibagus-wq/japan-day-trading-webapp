from agents.base import Agent, valid


class BreakoutAgent(Agent):
    """Opening-range / prior-day level breaks and Bollinger squeeze releases, gated by relative volume."""
    key = "breakout"
    label = "Breakout (ORB/Squeeze)"

    def score(self, f):
        close, atr, rvol = f["close"], f["atr"], f["rvol"]
        if not valid(close, atr) or atr <= 0:
            return None, ["insufficient data"]
        s, reasons = 0.0, []

        if f.get("or_complete") and valid(f.get("or_high"), f.get("or_low")):
            if close > f["or_high"]:
                s += 40; reasons.append("above opening-range high")
            elif close < f["or_low"]:
                s -= 40; reasons.append("below opening-range low")

        pdh, pdl = f.get("prev_day_high"), f.get("prev_day_low")
        if valid(pdh) and close > pdh:
            s += 25; reasons.append("above prior-day high")
        elif valid(pdl) and close < pdl:
            s -= 25; reasons.append("below prior-day low")

        pct_b = f.get("bb_pct_b")
        if f.get("squeeze") and valid(pct_b):
            if pct_b > 1.0:
                s += 30; reasons.append("squeeze release up")
            elif pct_b < 0.0:
                s -= 30; reasons.append("squeeze release down")

        # Breakouts without participation are unreliable: scale by relative volume
        if valid(rvol):
            if rvol < 0.8:
                s *= 0.4; reasons.append(f"low RVol {rvol:.2f}x — weak participation")
            elif rvol >= 1.5:
                s *= 1.3; reasons.append(f"RVol {rvol:.2f}x confirms")
        return s, reasons
