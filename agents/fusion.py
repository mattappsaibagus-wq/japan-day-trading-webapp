from agents.trend_agent import TrendAgent
from agents.momentum_agent import MomentumAgent
from agents.breakout_agent import BreakoutAgent
from agents.vwap_agent import VWAPAgent
from agents.macro_agent import MacroAgent

SIGNALS = [
    # (min score, signal, jp, mark, action)
    (45, "STRONG BUY", "強い買い", "◎", "BUY"),
    (18, "BUY", "買い", "○", "BUY"),
    (-18, "HOLD", "様子見", "△", "HOLD"),
    (-45, "SELL", "売り", "▼", "SELL"),
    (-1000, "STRONG SELL", "強い売り", "×", "SELL"),
]


def classify(score):
    for threshold, signal, jp, mark, action in SIGNALS:
        if score > threshold or threshold == -1000:
            return signal, jp, mark, action
    return "HOLD", "様子見", "△", "HOLD"


class AgentFusion:
    def __init__(self, agents):
        self.agents = agents

    def run_all(self, features):
        outputs = [a.analyze(features) for a in self.agents]
        # Agents that can't score (e.g. VWAP on daily bars) drop out of the weighting
        active = [o for o in outputs if o["active"]]
        total_w = sum(o["weight"] for o in active) or 1.0
        score = sum(o["score"] * o["weight"] for o in active) / total_w

        # Confidence = weighted share of agents agreeing with the fused direction
        if abs(score) < 1e-9:
            agree = 0.0
        else:
            agree = sum(o["weight"] for o in active if o["score"] * score > 0) / total_w
        signal, jp, mark, action = classify(score)
        return {
            "final_score": round(score, 1),
            "final_signal": signal,
            "final_signal_jp": jp,
            "final_mark": mark,
            "final_action": action,
            "agreement": round(agree * 100, 1),
            "agents": outputs,
        }


def default_fusion():
    return AgentFusion([
        TrendAgent(weight=0.8),
        MomentumAgent(weight=0.6),
        BreakoutAgent(weight=0.6),
        VWAPAgent(weight=0.7),
        MacroAgent(weight=0.3),
    ])
