"""Rule-based signal agents. Each agent scores a feature dict on -100..+100."""

from agents.base import Agent
from agents.trend_agent import TrendAgent
from agents.momentum_agent import MomentumAgent
from agents.breakout_agent import BreakoutAgent
from agents.vwap_agent import VWAPAgent
from agents.macro_agent import MacroAgent
from agents.fusion import AgentFusion, default_fusion

__all__ = ["Agent", "TrendAgent", "MomentumAgent", "BreakoutAgent", "VWAPAgent",
           "MacroAgent", "AgentFusion", "default_fusion"]
