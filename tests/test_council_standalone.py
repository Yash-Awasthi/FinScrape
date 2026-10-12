"""Test standalone import of the council package."""
import pytest


def test_council_package_imports():
    """Verify the council package can be imported without finscrape dependencies."""
    from finscrape.council import AgentCouncil, CouncilVerdict, BaseAgent, AgentVerdict
    from finscrape.council.protocols import AiClient, CouncilEvent
    from finscrape.council.personas import DEFAULT_AGENTS, AnalystAgent, ContrarianAgent

    assert AgentCouncil is not None
    assert CouncilVerdict is not None
    assert BaseAgent is not None
    assert AgentVerdict is not None
    assert len(DEFAULT_AGENTS) == 8


def test_agent_verdict_clamping():
    """AgentVerdict clamps score and confidence to valid ranges."""
    from finscrape.council.base import AgentVerdict

    v = AgentVerdict(agent_name="test", verdict="INVEST", signal_score=99, confidence=5.0)
    assert v.signal_score == 5
    assert v.confidence == 1.0

    v2 = AgentVerdict(agent_name="test", verdict="PULL_OUT", signal_score=-99, confidence=-1.0)
    assert v2.signal_score == -5
    assert v2.confidence == 0.0


def test_verdict_from_score():
    """Score-to-verdict mapping works correctly."""
    from finscrape.council.base import AgentVerdict

    assert AgentVerdict._verdict_from_score(5) == "INVEST"
    assert AgentVerdict._verdict_from_score(3) == "INVEST"
    assert AgentVerdict._verdict_from_score(2) == "OBSERVE"
    assert AgentVerdict._verdict_from_score(1) == "OBSERVE"
    assert AgentVerdict._verdict_from_score(0) == "OBSERVE"
    assert AgentVerdict._verdict_from_score(-1) == "CAUTIOUS"
    assert AgentVerdict._verdict_from_score(-3) == "PULL_OUT"


def test_council_verdict_to_dict():
    """CouncilVerdict serializes correctly."""
    from finscrape.council.council import CouncilVerdict

    v = CouncilVerdict(consensus_score=3.5, consensus_verdict="INVEST")
    d = v.to_dict()
    assert d["consensus_score"] == 3.5
    assert d["consensus_verdict"] == "INVEST"
    assert isinstance(d["individual_verdicts"], list)


def test_council_requires_agents():
    """AgentCouncil raises ValueError with no agents."""
    from finscrape.council.council import AgentCouncil

    with pytest.raises(ValueError, match="at least one agent"):
        AgentCouncil(agents=[], ai_client=lambda *a: None)


def test_council_deliberate_with_mock():
    """AgentCouncil.deliberate() works with a mock AI client."""
    from finscrape.council.council import AgentCouncil
    from finscrape.council.personas import AnalystAgent

    def mock_ai(prompt, system, model=None):
        return {
            "verdict": "OBSERVE",
            "signal_score": 2,
            "confidence": 0.7,
            "reasoning": "Test analysis",
            "tickers": ["TEST"],
            "risk_factors": ["test risk"],
            "key_insights": ["test insight"],
        }

    council = AgentCouncil(agents=[AnalystAgent()], ai_client=mock_ai)
    verdict = council.deliberate("Test headline", "Test article body")

    assert verdict.consensus_verdict == "OBSERVE"
    assert verdict.consensus_score == 2
    assert verdict.consensus_confidence > 0
    assert len(verdict.individual_verdicts) == 1
