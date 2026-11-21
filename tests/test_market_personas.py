"""
Tests for the Market Persona Simulation agents (Phase 3).

All tests use mocked AI responses — no actual API calls are made.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out finscrape.analysis.ai_client so we never import requests/dotenv
# at module level (same pattern as test_agents.py).
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

from finscrape.agents.base import BaseAgent
from finscrape.agents.council import AgentCouncil
from finscrape.agents.market_personas import (
    MARKET_PERSONAS,
    ContrarianInvestorAgent,
    ESGInvestorAgent,
    InstitutionalWhaleAgent,
    QuantAgent,
    RetailDayTraderAgent,
)
from finscrape.agents.personas import DEFAULT_AGENTS

# Drop the stub so later test modules importing the real ai_client don't
# inherit this MagicMock-only module from sys.modules.
del sys.modules["finscrape.analysis.ai_client"]


# ===================================================================
# Persona property tests
# ===================================================================

class TestInstitutionalWhaleAgent:

    def test_name(self):
        agent = InstitutionalWhaleAgent(weight=1.3)
        assert agent.name == "institutional_whale"

    def test_weight(self):
        agent = InstitutionalWhaleAgent(weight=1.3)
        assert agent.weight == 1.3

    def test_role_is_non_empty(self):
        agent = InstitutionalWhaleAgent()
        assert len(agent.role) > 10

    def test_system_prompt_keywords(self):
        agent = InstitutionalWhaleAgent()
        prompt = agent.system_prompt.lower()
        assert "institutional" in prompt
        assert "capital preservation" in prompt
        assert "fundamentals" in prompt
        assert "long-term" in prompt or "long term" in prompt
        assert "management" in prompt
        assert "liquidity" in prompt
        assert "earnings quality" in prompt


class TestRetailDayTraderAgent:

    def test_name(self):
        agent = RetailDayTraderAgent(weight=0.6)
        assert agent.name == "retail_day_trader"

    def test_weight(self):
        agent = RetailDayTraderAgent(weight=0.6)
        assert agent.weight == 0.6

    def test_role_is_non_empty(self):
        agent = RetailDayTraderAgent()
        assert len(agent.role) > 10

    def test_system_prompt_keywords(self):
        agent = RetailDayTraderAgent()
        prompt = agent.system_prompt.lower()
        assert "momentum" in prompt
        assert "volatility" in prompt
        assert "volume" in prompt
        assert "short-term" in prompt or "short term" in prompt
        assert "social" in prompt
        assert "catalyst" in prompt


class TestContrarianInvestorAgent:

    def test_name(self):
        agent = ContrarianInvestorAgent(weight=0.9)
        assert agent.name == "contrarian_investor"

    def test_weight(self):
        agent = ContrarianInvestorAgent(weight=0.9)
        assert agent.weight == 0.9

    def test_role_is_non_empty(self):
        agent = ContrarianInvestorAgent()
        assert len(agent.role) > 10

    def test_system_prompt_keywords(self):
        agent = ContrarianInvestorAgent()
        prompt = agent.system_prompt.lower()
        assert "contrarian" in prompt
        assert "mean reversion" in prompt
        assert "overreaction" in prompt
        assert "fear" in prompt
        assert "greed" in prompt
        assert "consensus" in prompt


class TestQuantAgent:

    def test_name(self):
        agent = QuantAgent(weight=1.1)
        assert agent.name == "quant"

    def test_weight(self):
        agent = QuantAgent(weight=1.1)
        assert agent.weight == 1.1

    def test_role_is_non_empty(self):
        agent = QuantAgent()
        assert len(agent.role) > 10

    def test_system_prompt_keywords(self):
        agent = QuantAgent()
        prompt = agent.system_prompt.lower()
        assert "quantitative" in prompt or "data-driven" in prompt
        assert "statistical" in prompt
        assert "standard deviation" in prompt
        assert "anomal" in prompt  # anomaly/anomalies
        assert "factor" in prompt
        assert "narrative" in prompt  # ignores narrative


class TestESGInvestorAgent:

    def test_name(self):
        agent = ESGInvestorAgent(weight=0.7)
        assert agent.name == "esg_investor"

    def test_weight(self):
        agent = ESGInvestorAgent(weight=0.7)
        assert agent.weight == 0.7

    def test_role_is_non_empty(self):
        agent = ESGInvestorAgent()
        assert len(agent.role) > 10

    def test_system_prompt_keywords(self):
        agent = ESGInvestorAgent()
        prompt = agent.system_prompt.lower()
        assert "environmental" in prompt
        assert "social" in prompt
        assert "governance" in prompt
        assert "esg" in prompt
        assert "reputational" in prompt
        assert "regulatory" in prompt
        assert "sustainability" in prompt or "sustainable" in prompt
        assert "greenwashing" in prompt


# ===================================================================
# MARKET_PERSONAS list tests
# ===================================================================

class TestMarketPersonasList:

    def test_market_personas_has_five_agents(self):
        assert len(MARKET_PERSONAS) == 5

    def test_all_agents_are_base_agent_subclasses(self):
        for agent in MARKET_PERSONAS:
            assert isinstance(agent, BaseAgent)

    def test_agent_names_are_unique(self):
        names = [a.name for a in MARKET_PERSONAS]
        assert len(names) == len(set(names))

    def test_expected_agent_types_present(self):
        types_present = {type(a) for a in MARKET_PERSONAS}
        expected = {
            InstitutionalWhaleAgent,
            RetailDayTraderAgent,
            ContrarianInvestorAgent,
            QuantAgent,
            ESGInvestorAgent,
        }
        assert types_present == expected

    def test_weights_match_spec(self):
        weight_map = {a.name: a.weight for a in MARKET_PERSONAS}
        assert weight_map["institutional_whale"] == 1.3
        assert weight_map["retail_day_trader"] == 0.6
        assert weight_map["contrarian_investor"] == 0.9
        assert weight_map["quant"] == 1.1
        assert weight_map["esg_investor"] == 0.7

    def test_all_weights_are_positive(self):
        for agent in MARKET_PERSONAS:
            assert agent.weight > 0, f"{agent.name} has non-positive weight"

    def test_each_agent_has_non_empty_system_prompt(self):
        for agent in MARKET_PERSONAS:
            assert len(agent.system_prompt) > 100, f"{agent.name} system prompt too short"

    def test_each_agent_has_role(self):
        for agent in MARKET_PERSONAS:
            assert len(agent.role) > 10, f"{agent.name} role too short"

    def test_no_name_collisions_with_default_agents(self):
        default_names = {a.name for a in DEFAULT_AGENTS}
        persona_names = {a.name for a in MARKET_PERSONAS}
        assert default_names.isdisjoint(persona_names), (
            f"Name collision: {default_names & persona_names}"
        )


# ===================================================================
# Council with market personas (mocked call_ai)
# ===================================================================

class TestCouncilWithMarketPersonas:

    def _mock_response_for_agent(self, agent_name: str) -> dict:
        """Return a plausible mock response keyed by agent name."""
        responses = {
            "institutional_whale": {
                "verdict": "OBSERVE",
                "signal_score": 2,
                "confidence": 0.75,
                "reasoning": "Solid earnings but need to see sustained execution.",
                "tickers": ["AAPL"],
                "risk_factors": ["Execution risk"],
                "key_insights": ["Strong cash flow generation"],
            },
            "retail_day_trader": {
                "verdict": "INVEST",
                "signal_score": 4,
                "confidence": 0.8,
                "reasoning": "Strong catalyst, volume surge expected.",
                "tickers": ["AAPL"],
                "risk_factors": [],
                "key_insights": ["Momentum breakout", "Social buzz rising"],
            },
            "contrarian_investor": {
                "verdict": "CAUTIOUS",
                "signal_score": -1,
                "confidence": 0.65,
                "reasoning": "Market already priced in the good news.",
                "tickers": ["AAPL"],
                "risk_factors": ["Crowded trade", "Mean reversion risk"],
                "key_insights": [],
            },
            "quant": {
                "verdict": "OBSERVE",
                "signal_score": 2,
                "confidence": 0.85,
                "reasoning": "1.5 std dev positive earnings surprise.",
                "tickers": ["AAPL"],
                "risk_factors": [],
                "key_insights": ["Statistically significant beat"],
            },
            "esg_investor": {
                "verdict": "CAUTIOUS",
                "signal_score": 0,
                "confidence": 0.6,
                "reasoning": "Financials positive but supply chain ESG concerns.",
                "tickers": ["AAPL"],
                "risk_factors": ["Supply chain labor practices"],
                "key_insights": [],
            },
        }
        return responses.get(agent_name, {
            "verdict": "CAUTIOUS",
            "signal_score": 0,
            "confidence": 0.5,
            "reasoning": "Default.",
            "tickers": [],
            "risk_factors": [],
            "key_insights": [],
        })

    def _make_mock_call_ai(self, agent_name_map: dict[str, str]):
        """Create a mock call_ai that routes by system prompt markers."""
        def mock_call_ai(prompt, system_prompt, model=None):
            lower = system_prompt.lower()
            for marker, name in agent_name_map.items():
                if marker in lower:
                    return self._mock_response_for_agent(name)
            return self._mock_response_for_agent("unknown")
        return mock_call_ai

    def test_council_with_market_personas(self):
        """Council with all 5 market personas produces valid consensus."""
        markers = {
            "institutional portfolio manager": "institutional_whale",
            "retail day trader": "retail_day_trader",
            "deep contrarian investor": "contrarian_investor",
            "quantitative analyst": "quant",
            "esg-focused investor": "esg_investor",
        }
        mock_fn = self._make_mock_call_ai(markers)

        with patch("finscrape.agents.base.call_ai", side_effect=mock_fn):
            council = AgentCouncil(agents=MARKET_PERSONAS)
            result = council.deliberate(
                "Apple Reports Record Q4 Earnings",
                "Apple Inc reported quarterly revenue of $89.5 billion...",
                metadata={"source": "reuters"},
            )

        assert len(result.individual_verdicts) == 5
        assert -5 <= result.consensus_score <= 5
        assert 0.0 <= result.consensus_confidence <= 1.0
        assert 0.0 <= result.agreement_level <= 1.0
        assert result.consensus_verdict in ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT")
        assert isinstance(result.dissenting_agents, list)
        assert isinstance(result.key_risks, list)
        assert isinstance(result.key_opportunities, list)

    def test_council_verdict_names_match_personas(self):
        """Each individual verdict should carry the correct agent name."""
        markers = {
            "institutional portfolio manager": "institutional_whale",
            "retail day trader": "retail_day_trader",
            "deep contrarian investor": "contrarian_investor",
            "quantitative analyst": "quant",
            "esg-focused investor": "esg_investor",
        }
        mock_fn = self._make_mock_call_ai(markers)

        with patch("finscrape.agents.base.call_ai", side_effect=mock_fn):
            council = AgentCouncil(agents=MARKET_PERSONAS)
            result = council.deliberate("Test", "Test body")

        verdict_names = {v.agent_name for v in result.individual_verdicts}
        expected_names = {a.name for a in MARKET_PERSONAS}
        assert verdict_names == expected_names


# ===================================================================
# Mixed council: DEFAULT_AGENTS + MARKET_PERSONAS
# ===================================================================

class TestMixedCouncil:

    def test_mixed_council_runs_all_agents(self):
        """Council with both DEFAULT_AGENTS and MARKET_PERSONAS works correctly."""
        combined = DEFAULT_AGENTS + MARKET_PERSONAS
        total_expected = len(DEFAULT_AGENTS) + len(MARKET_PERSONAS)

        # Generic mock that returns a safe response for any agent
        def mock_call_ai(prompt, system_prompt, model=None):
            return {
                "verdict": "OBSERVE",
                "signal_score": 1,
                "confidence": 0.7,
                "reasoning": "Mock analysis.",
                "tickers": ["TEST"],
                "risk_factors": ["mock risk"],
                "key_insights": ["mock insight"],
            }

        with patch("finscrape.agents.base.call_ai", side_effect=mock_call_ai):
            council = AgentCouncil(agents=combined)
            result = council.deliberate(
                "Test Mixed Council",
                "Testing combined agent roster.",
            )

        assert len(result.individual_verdicts) == total_expected
        assert -5 <= result.consensus_score <= 5
        assert 0.0 <= result.consensus_confidence <= 1.0
        assert result.consensus_verdict in ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT")

    def test_mixed_council_names_are_all_unique(self):
        """No name collisions when combining both agent lists."""
        combined = DEFAULT_AGENTS + MARKET_PERSONAS
        names = [a.name for a in combined]
        assert len(names) == len(set(names))

    def test_mixed_council_weighted_correctly(self):
        """Verify weights are preserved in the combined council."""
        combined = DEFAULT_AGENTS + MARKET_PERSONAS
        council = AgentCouncil(agents=combined)
        weight_map = {a.name: a.weight for a in council.agents}

        # Spot-check a few weights from each list
        assert weight_map["institutional_whale"] == 1.3
        assert weight_map["retail_day_trader"] == 0.6
        assert weight_map["quant"] == 1.1
