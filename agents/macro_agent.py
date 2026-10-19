from agents.base import Agent, valid


class MacroAgent(Agent):
    """Nikkei direction plus USD/JPY, scaled by the stock's FX sensitivity (exporters gain from a weaker yen)."""
    key = "macro"
    label = "Macro (N225/USDJPY)"

    def score(self, f):
        nk, fx = f.get("nikkei_chg"), f.get("usdjpy_chg")
        if not valid(nk, fx):
            return None, ["macro data unavailable"]
        beta = f.get("fx_beta", 0.0) or 0.0
        s = nk * 35 + fx * 60 * beta
        reasons = [f"Nikkei {nk:+.2f}%", f"USD/JPY {fx:+.2f}% × FX beta {beta:+.1f}"]
        return s, reasons
