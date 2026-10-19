import math


def clamp(x, lo=-100.0, hi=100.0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return max(lo, min(hi, x))


def valid(*vals):
    return all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals)


class Agent:
    key = "base"
    label = "Base"

    def __init__(self, weight=1.0):
        self.weight = weight

    def score(self, f):
        """Return (score in -100..100, reasons). Score None means the agent can't judge this bar."""
        raise NotImplementedError

    def analyze(self, features):
        score, reasons = self.score(features)
        return {
            "agent": self.key,
            "label": self.label,
            "weight": self.weight,
            "active": score is not None,
            "score": round(clamp(score), 1) if score is not None else 0.0,
            "reasons": reasons,
        }
