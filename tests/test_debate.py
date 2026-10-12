"""
Tests for multi-round agent debate: round 1 stays blind and parallel,
round 2+ gives each agent a fenced transcript of the other agents' prior
verdicts and lets it rebut and re-emit its own verdict.

All tests use a stubbed call_ai — no network, no LLM.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Same stubbing trick as tests/test_agents.py: fake out
# finscrape.analysis.ai_client before importing the agents package.
# ---------------------------------------------------------------------------
_ai_client_mod = types.ModuleType("finscrape.analysis.ai_client")
_ai_client_mod.call_ai = MagicMock(return_value=None)
sys.modules["finscrape.analysis.ai_client"] = _ai_client_mod

import finscrape.analysis.constants  # noqa: F401
from finscrape.agents.base import AgentVerdict, BaseAgent
from finscrape.agents.council import COUNCIL_ROUNDS_ENV_VAR, AgentCouncil
from finscrape.analysis.prompts import ARTICLE_FENCE_START

del sys.modules["finscrape.analysis.ai_client"]


class StanceAgent(BaseAgent):
    """Minimal concrete agent with a unique, identifiable system prompt."""

    def __init__(self, agent_name: str, weight: float = 1.0):
        super().__init__(weight=weight)
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return f"Test stance agent '{self._name}'."

    @property
    def system_prompt(self) -> str:
        return f"You are test stance agent MARKER_{self._name.upper()}."


# Two agents start bullish (+4), two start bearish (-4) in round 1 — a clean
# 50/50 split. In round 2 every agent flips to unanimous +5 after seeing the
# opposing transcript, so the round-2 consensus (5.0) cannot be produced by
# accidentally reusing round-1 numbers (which average to 0.0).
ROUND_1_SCORES = {"bull_a": 4, "bull_b": 4, "bear_a": -4, "bear_b": -4}
ROUND_2_SCORES = {"bull_a": 5, "bull_b": 5, "bear_a": 5, "bear_b": 5}

AGENT_NAMES = list(ROUND_1_SCORES)


def _agent_for_system_prompt(system_prompt: str) -> str:
    for name in AGENT_NAMES:
        if f"MARKER_{name.upper()}" in system_prompt:
            return name
    raise AssertionError(f"no marker matched system prompt: {system_prompt!r}")


def _make_agents() -> list[StanceAgent]:
    return [StanceAgent(name) for name in AGENT_NAMES]


def _make_stub(captured_round2_prompts: dict):
    """Build a call_ai stub: round 1 by score table, round 2 by score table,
    capturing every round-2 prompt so the test can inspect it afterwards."""

    def _stub(prompt, system_prompt, model=None):
        agent = _agent_for_system_prompt(system_prompt)
        is_round_2 = ARTICLE_FENCE_START in prompt
        if is_round_2:
            captured_round2_prompts[agent] = prompt
            score = ROUND_2_SCORES[agent]
        else:
            score = ROUND_1_SCORES[agent]
        return {
            "verdict": AgentVerdict._verdict_from_score(score),
            "signal_score": score,
            "confidence": 0.7,
            "reasoning": f"{agent} stance at this round.",
            "tickers": [],
            "risk_factors": [],
            "key_insights": [],
        }

    return _stub


class TestDebateRounds:

    def test_round_1_is_blind_and_unaffected_by_rounds_setting(self, monkeypatch):
        """rounds=1 output must be identical to today's single-pass behavior."""
        monkeypatch.delenv(COUNCIL_ROUNDS_ENV_VAR, raising=False)
        captured: dict = {}
        stub = _make_stub(captured)

        with monkeypatch.context() as m:
            m.setattr("finscrape.agents.base.call_ai", stub)
            explicit = AgentCouncil(agents=_make_agents(), rounds=1).deliberate("H", "B")
            default = AgentCouncil(agents=_make_agents()).deliberate("H", "B")

        # No agent ever saw a transcript in either run.
        assert captured == {}
        assert not explicit.judged
        assert explicit.consensus_score == default.consensus_score == 0.0
        assert explicit.consensus_verdict == default.consensus_verdict == "OBSERVE"
        assert len(explicit.score_history) == len(default.score_history) == 1
        assert explicit.score_history[0] == ROUND_1_SCORES
        assert default.score_history[0] == ROUND_1_SCORES

    def test_round_2_prompt_contains_opponent_names_and_round_1_scores(self, monkeypatch):
        captured: dict = {}
        stub = _make_stub(captured)
        monkeypatch.setattr("finscrape.agents.base.call_ai", stub)

        AgentCouncil(agents=_make_agents(), rounds=2).deliberate("H", "B")

        assert set(captured) == set(AGENT_NAMES)
        for agent, prompt in captured.items():
            for opponent in AGENT_NAMES:
                if opponent == agent:
                    continue
                assert opponent in prompt, f"{agent}'s round-2 prompt is missing opponent {opponent}"
                assert f"score={ROUND_1_SCORES[opponent]}" in prompt, (
                    f"{agent}'s round-2 prompt is missing {opponent}'s round-1 score"
                )
            # An agent never argues against itself.
            assert prompt.count(f"- {agent}: score=") == 0

    def test_final_consensus_comes_from_round_2_not_round_1(self, monkeypatch):
        captured: dict = {}
        stub = _make_stub(captured)
        monkeypatch.setattr("finscrape.agents.base.call_ai", stub)

        result = AgentCouncil(agents=_make_agents(), rounds=2).deliberate("H", "B")

        # Round 1 alone averages to 0.0 (two +4, two -4); only round 2's
        # unanimous +5 explains this consensus.
        assert result.consensus_score == 5.0
        assert result.consensus_verdict == "INVEST"
        assert len(result.score_history) == 2
        assert result.score_history[0] == ROUND_1_SCORES
        assert result.score_history[1] == ROUND_2_SCORES
        for v in result.individual_verdicts:
            assert v.signal_score == 5

    def test_rounds_opt_in_via_env_var(self, monkeypatch):
        captured: dict = {}
        stub = _make_stub(captured)
        monkeypatch.setattr("finscrape.agents.base.call_ai", stub)
        monkeypatch.setenv(COUNCIL_ROUNDS_ENV_VAR, "2")

        result = AgentCouncil(agents=_make_agents()).deliberate("H", "B")

        assert len(result.score_history) == 2
        assert result.consensus_score == 5.0

    def test_agent_can_change_its_mind_between_rounds(self, monkeypatch):
        """Per-agent score_history entries can legitimately differ round to round."""
        captured: dict = {}
        stub = _make_stub(captured)
        monkeypatch.setattr("finscrape.agents.base.call_ai", stub)

        result = AgentCouncil(agents=_make_agents(), rounds=2).deliberate("H", "B")

        for name in AGENT_NAMES:
            assert result.score_history[0][name] != result.score_history[1][name]
