"""
Multi-Agent AI Council for financial news analysis.

Provides multiple AI personas that independently analyze articles and
produce a consensus verdict through weighted deliberation.

Quick start:
    from finscrape.agents import AgentCouncil, DEFAULT_AGENTS

    council = AgentCouncil(agents=DEFAULT_AGENTS)
    verdict = council.deliberate(title, text, metadata)
"""

from finscrape.agents.base import AgentVerdict, BaseAgent
from finscrape.agents.council import AgentCouncil, CouncilVerdict
from finscrape.agents.judge import JudgeVerdict, judge_debate
from finscrape.agents.market_personas import (
    MARKET_PERSONAS,
    ContrarianInvestorAgent,
    ESGInvestorAgent,
    InstitutionalWhaleAgent,
    QuantAgent,
    RetailDayTraderAgent,
)
from finscrape.agents.personas import (
    DEFAULT_AGENTS,
    AnalystAgent,
    ContrarianAgent,
    FundamentalsAgent,
    MomentumAgent,
    ReviewerAgent,
    RiskAgent,
    ScoutAgent,
    TechnicalAgent,
)

__all__ = [
    "DEFAULT_AGENTS",
    "MARKET_PERSONAS",
    "AgentCouncil",
    "AgentVerdict",
    "AnalystAgent",
    "BaseAgent",
    "ContrarianAgent",
    "ContrarianInvestorAgent",
    "CouncilVerdict",
    "ESGInvestorAgent",
    "FundamentalsAgent",
    "InstitutionalWhaleAgent",
    "JudgeVerdict",
    "MomentumAgent",
    "QuantAgent",
    "RetailDayTraderAgent",
    "ReviewerAgent",
    "RiskAgent",
    "ScoutAgent",
    "TechnicalAgent",
    "judge_debate",
]
