"""
AgentCouncil — runs multiple AI agents in parallel and produces a consensus verdict.

The council:
  1. Dispatches the article to all agents concurrently via ThreadPoolExecutor.
  2. Collects individual AgentVerdict results.
  3. Computes a weighted consensus score, confidence, and verdict.
  4. Identifies dissenting agents and agreement level.
"""

from __future__ import annotations

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any

from finscrape.agents.base import AgentVerdict, BaseAgent
from finscrape.agents.judge import judge_debate

logger = logging.getLogger(__name__)

# Maximum possible standard deviation for scores in [-5, 5] range.
# Occurs when half the agents score +5 and half score -5.
# For a uniform population of {-5, +5}: std_dev = 5.0
MAX_POSSIBLE_STD_DEV = 5.0

# Threshold: if an agent's score differs from consensus by more than this,
# it is considered a dissenter.
DISSENT_THRESHOLD = 2.5

# Env var opt-in for debate rounds. Unset means rounds=1 (blind single pass),
# which existing callers and tests depend on staying byte-identical.
COUNCIL_ROUNDS_ENV_VAR = "FINSCRAPE_COUNCIL_ROUNDS"


@dataclass
class CouncilVerdict:
    """Aggregated output from the full agent council deliberation."""

    individual_verdicts: list[AgentVerdict] = field(default_factory=list)
    consensus_score: float = 0.0  # weighted average, [-5, 5] — judge-overridden when judged
    consensus_confidence: float = 0.0  # [0.0, 1.0]
    consensus_verdict: str = "CAUTIOUS"  # INVEST / OBSERVE / CAUTIOUS / PULL_OUT
    agreement_level: float = 0.0  # [0.0, 1.0]; 1 = perfect agreement
    dissenting_agents: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    key_opportunities: list[str] = field(default_factory=list)
    failed_agents: int = 0
    consensus_score_raw: float = 0.0  # weighted mean, always the arithmetic value
    judge_rationale: str = ""
    judged: bool = False
    score_history: list[dict[str, int]] = field(default_factory=list)  # one {agent: score} dict per round

    def to_dict(self) -> dict:
        d = asdict(self)
        d["individual_verdicts"] = [v.to_dict() for v in self.individual_verdicts]
        return d


class AgentCouncil:
    """
    Orchestrates multiple agents to deliberate on a financial news article.

    Usage:
        council = AgentCouncil(agents=[AnalystAgent(), ContrarianAgent(), ...])
        verdict = council.deliberate(title, text, metadata)
    """

    def __init__(
        self,
        agents: list[BaseAgent],
        max_workers: int | None = None,
        judge: bool = False,
        rounds: int | None = None,
    ):
        if not agents:
            raise ValueError("AgentCouncil requires at least one agent.")
        self.agents = agents
        self.max_workers = max_workers or min(len(agents), 8)
        self.judge = judge
        if rounds is None:
            rounds = int(os.environ.get(COUNCIL_ROUNDS_ENV_VAR, "1"))
        self.rounds = max(1, rounds)

    def deliberate(
        self,
        title: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        market_facts: dict[str, dict] | None = None,
        lessons: dict[str, Any] | None = None,
    ) -> CouncilVerdict:
        """
        Run all agents in parallel and produce a consensus verdict.

        Round 1 is blind. From round 2 on (opt-in via `rounds`), each agent
        gets a fenced transcript of every other agent's prior-round verdict
        and re-answers, one parallel dispatch per round.

        The council fetches nothing itself: `market_facts` (per-ticker computed
        indicators from finscrape.market_data.get_indicators) is resolved by the
        caller and handed straight to the agents, so the council stays pure and
        offline-testable.

        Args:
            title: Article headline.
            text: Article body text.
            metadata: Optional dict of extra context (source, age, etc.).
            market_facts: Optional {ticker: {indicator: value}} GROUND TRUTH facts.
            lessons: Optional grounded past-call stats, folded into
                the judge's prompt only — debators never see it.

        Returns:
            CouncilVerdict built from the final round's verdicts.
        """
        verdicts = self._run_agents(title, text, metadata, market_facts)
        score_history = [self._score_snapshot(verdicts)]

        for round_num in range(2, self.rounds + 1):
            verdicts = self._run_rebuttal_round(title, text, metadata, verdicts, round_num, market_facts)
            score_history.append(self._score_snapshot(verdicts))

        result = self._build_consensus(verdicts, lessons)
        result.score_history = score_history
        return result

    @staticmethod
    def _score_snapshot(verdicts: list[AgentVerdict]) -> dict[str, int]:
        return {v.agent_name: v.signal_score for v in verdicts}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_agents(
        self,
        title: str,
        text: str,
        metadata: dict[str, Any] | None,
        market_facts: dict[str, dict] | None = None,
    ) -> list[AgentVerdict]:
        """Execute all agents concurrently and collect verdicts."""
        verdicts: list[AgentVerdict] = []

        # Appends market_facts only when set, so an agent.analyze() override that
        # only takes (title, text, metadata) keeps working unchanged.
        analyze_args = (title, text, metadata) if market_facts is None else (title, text, metadata, market_facts)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_agent = {
                executor.submit(agent.analyze, *analyze_args): agent
                for agent in self.agents
            }

            for future in as_completed(future_to_agent):
                agent = future_to_agent[future]
                try:
                    verdict = future.result()
                    verdicts.append(verdict)
                    logger.info(
                        "[Council] %s: score=%d conf=%.2f verdict=%s",
                        agent.name, verdict.signal_score,
                        verdict.confidence, verdict.verdict,
                    )
                except Exception as e:
                    logger.error("[Council] Agent '%s' raised exception: %s", agent.name, e)
                    verdicts.append(AgentVerdict(
                        agent_name=agent.name,
                        verdict="CAUTIOUS",
                        signal_score=0,
                        confidence=0.1,
                        reasoning=f"Agent '{agent.name}' failed with error: {e}",
                        error=True,
                    ))

        return verdicts

    def _run_rebuttal_round(
        self,
        title: str,
        text: str,
        metadata: dict[str, Any] | None,
        prior_verdicts: list[AgentVerdict],
        round_num: int,
        market_facts: dict[str, dict] | None = None,
    ) -> list[AgentVerdict]:
        """Every agent sees every other agent's prior-round verdict and re-answers, in parallel."""
        verdicts: list[AgentVerdict] = []
        rebut_tail = (metadata, round_num) if market_facts is None else (metadata, round_num, market_facts)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_agent = {
                executor.submit(
                    agent.rebut, title, text,
                    [v for v in prior_verdicts if v.agent_name != agent.name and not v.error],
                    *rebut_tail,
                ): agent
                for agent in self.agents
            }

            for future in as_completed(future_to_agent):
                agent = future_to_agent[future]
                try:
                    verdict = future.result()
                    verdicts.append(verdict)
                    logger.info(
                        "[Council] round %d %s: score=%d conf=%.2f verdict=%s",
                        round_num, agent.name, verdict.signal_score,
                        verdict.confidence, verdict.verdict,
                    )
                except Exception as e:
                    logger.error(
                        "[Council] round %d agent '%s' raised exception: %s",
                        round_num, agent.name, e,
                    )
                    verdicts.append(AgentVerdict(
                        agent_name=agent.name,
                        verdict="CAUTIOUS",
                        signal_score=0,
                        confidence=0.1,
                        reasoning=f"Agent '{agent.name}' failed with error: {e}",
                        error=True,
                    ))

        return verdicts

    def _build_consensus(
        self, verdicts: list[AgentVerdict], lessons: dict[str, Any] | None = None,
    ) -> CouncilVerdict:
        """Compute consensus metrics from individual agent verdicts."""
        if not verdicts:
            return CouncilVerdict()

        failed_agents = sum(1 for v in verdicts if v.error)
        survivors = [v for v in verdicts if not v.error]

        if not survivors:
            return CouncilVerdict(individual_verdicts=verdicts, failed_agents=failed_agents)

        # Build a mapping of agent name -> weight for the agents in the council
        agent_weights = {agent.name: agent.weight for agent in self.agents}

        # --- Weighted average score ---
        total_weight = 0.0
        weighted_score_sum = 0.0
        for v in survivors:
            w = agent_weights.get(v.agent_name, 1.0)
            weighted_score_sum += v.signal_score * w
            total_weight += w

        consensus_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0

        # --- Agreement level: 1 - (std_dev / max_possible_std_dev) ---
        scores = [v.signal_score for v in survivors]
        agreement_level = self._calculate_agreement(scores)

        # --- Consensus confidence ---
        # Start with weighted average confidence, then adjust by agreement
        weighted_conf_sum = 0.0
        for v in survivors:
            w = agent_weights.get(v.agent_name, 1.0)
            weighted_conf_sum += v.confidence * w

        base_confidence = weighted_conf_sum / total_weight if total_weight > 0 else 0.0

        # Boost confidence when agents agree, reduce when they disagree
        # agreement_level is [0, 1]; scale it to a multiplier of [0.6, 1.2]
        confidence_multiplier = 0.6 + (agreement_level * 0.6)
        consensus_confidence = max(0.0, min(1.0, base_confidence * confidence_multiplier))

        # Discount confidence per agent whose reasoning contradicts a computed
        # indicator (see AgentVerdict.number_conflict / validator.check_number_conflicts).
        flagged = sum(1 for v in survivors if v.number_conflict)
        if flagged:
            consensus_confidence = max(0.0, consensus_confidence - min(0.4, 0.1 * flagged))

        # --- Consensus verdict ---
        rounded_score = round(consensus_score)
        consensus_verdict = AgentVerdict._verdict_from_score(rounded_score)

        # --- Dissenting agents ---
        dissenting = [
            v.agent_name for v in survivors
            if abs(v.signal_score - consensus_score) > DISSENT_THRESHOLD
        ]

        # --- Aggregate risks and opportunities ---
        key_risks = []
        key_opportunities = []
        seen_risks: set[str] = set()
        seen_opps: set[str] = set()

        for v in survivors:
            for risk in v.risk_factors:
                normalized = risk.strip().lower()
                if normalized and normalized not in seen_risks:
                    seen_risks.add(normalized)
                    key_risks.append(risk.strip())
            for insight in v.key_insights:
                normalized = insight.strip().lower()
                if normalized and normalized not in seen_opps:
                    seen_opps.add(normalized)
                    key_opportunities.append(insight.strip())

        consensus_score_raw = round(consensus_score, 2)
        agreement_level = round(agreement_level, 2)

        final_score = consensus_score_raw
        final_confidence = round(consensus_confidence, 2)
        final_verdict = consensus_verdict
        judge_rationale = ""
        judged = False

        if self.judge:
            stats = {
                "consensus_score_raw": consensus_score_raw,
                "agreement_level": agreement_level,
                "dissenting_agents": dissenting,
            }
            jv = judge_debate(verdicts, stats, lessons)
            if jv is not None:
                final_score = jv.signal_score
                final_confidence = jv.confidence
                final_verdict = jv.verdict
                judge_rationale = jv.rationale
                judged = True

        return CouncilVerdict(
            individual_verdicts=verdicts,
            consensus_score=final_score,
            consensus_confidence=final_confidence,
            consensus_verdict=final_verdict,
            agreement_level=agreement_level,
            dissenting_agents=dissenting,
            key_risks=key_risks,
            key_opportunities=key_opportunities,
            failed_agents=failed_agents,
            consensus_score_raw=consensus_score_raw,
            judge_rationale=judge_rationale,
            judged=judged,
        )

    @staticmethod
    def _calculate_agreement(scores: list[int | float]) -> float:
        """
        Calculate agreement level from a list of scores.

        Returns a value between 0.0 (maximum disagreement) and 1.0 (perfect agreement).
        Formula: 1 - (std_dev / MAX_POSSIBLE_STD_DEV)
        """
        if len(scores) <= 1:
            return 1.0  # Single agent or empty — perfect "agreement"

        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)

        agreement = 1.0 - (std_dev / MAX_POSSIBLE_STD_DEV)
        return max(0.0, min(1.0, agreement))
