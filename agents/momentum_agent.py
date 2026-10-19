from agents.base import Agent, valid


class MomentumAgent(Agent):
    """RSI regime + MACD cross and histogram acceleration."""
    key = "momentum"
    label = "Momentum (RSI/MACD)"

    def score(self, f):
        rsi, macd, sig, hist, prev_hist, atr = (f["rsi"], f["macd"], f["macd_signal"],
                                               f["macd_hist"], f["prev_macd_hist"], f["atr"])
        if not valid(rsi, macd, sig, hist, prev_hist, atr) or atr <= 0:
            return None, ["insufficient data"]
        s, reasons = 0.0, []
        # RSI: 50-70 is healthy bullish momentum; >78 is stretched; mirror for the short side
        if rsi >= 78:
            s += 5; reasons.append(f"RSI {rsi:.0f} overbought — chasing risk")
        elif rsi >= 55:
            s += (rsi - 50) * 1.6; reasons.append(f"RSI {rsi:.0f} bullish regime")
        elif rsi <= 22:
            s -= 5; reasons.append(f"RSI {rsi:.0f} oversold — bounce risk")
        elif rsi <= 45:
            s -= (50 - rsi) * 1.6; reasons.append(f"RSI {rsi:.0f} bearish regime")

        s += 25 if macd > sig else -25
        accel = (hist - prev_hist) / atr
        s += max(-30, min(30, accel * 150))
        if hist > 0 and prev_hist <= 0:
            reasons.append("MACD bullish cross")
        elif hist < 0 and prev_hist >= 0:
            reasons.append("MACD bearish cross")
        return s, reasons
