from agents.base import Agent, valid


class TrendAgent(Agent):
    """EMA 9/21/50 stack and the slope of EMA21."""
    key = "trend"
    label = "Trend (EMA stack)"

    def score(self, f):
        close, e9, e21, e50, atr = f["close"], f["ema9"], f["ema21"], f["ema50"], f["atr"]
        if not valid(close, e9, e21, e50, atr) or atr <= 0:
            return None, ["insufficient data"]
        s, reasons = 0.0, []
        if e9 > e21 > e50:
            s += 45; reasons.append("EMA9 > EMA21 > EMA50 (bullish stack)")
        elif e9 < e21 < e50:
            s -= 45; reasons.append("EMA9 < EMA21 < EMA50 (bearish stack)")
        elif e9 > e21:
            s += 15; reasons.append("EMA9 above EMA21")
        elif e9 < e21:
            s -= 15; reasons.append("EMA9 below EMA21")

        # Price distance from EMA21 in ATR units, capped so extended moves don't dominate
        dist = (close - e21) / atr
        s += max(-30, min(30, dist * 15))

        slope = f.get("ema21_slope")
        if valid(slope):
            s += max(-25, min(25, slope / atr * 60))
            if abs(slope) > 0.1 * atr:
                reasons.append(f"EMA21 sloping {'up' if slope > 0 else 'down'}")
        return s, reasons
