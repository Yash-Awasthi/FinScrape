"""
Judge — reads the whole council debate transcript plus the arithmetic
consensus (mean, agreement, dissenter list) and reasons about why the
agents disagree, then hands down its own score/confidence/verdict.

The judge can agree with the arithmetic mean or override it outright.
When the judge LLM is unreachable, judge_debate() returns None and the
caller falls straight back to the arithmetic consensus — zero regression.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any

from finscrape.agents.base import AgentVerdict
from finscrape.analysis.ai_client import call_ai

logger = logging.getLogger(__name__)

JUDGE_MODEL_ENV = "FINSCRAPE_JUDGE_MODEL"

JUDGE_RESPONSE_SCHEMA = """\
{
  "verdict": "INVEST/OBSERVE/CAUTIOUS/PULL_OUT",
  "signal_score": integer from -5 to 5,
  "confidence": float from 0.0 to 1.0,
  "rationale": "why the agents disagree and why you land where you do"
}"""

JUDGE_SYSTEM_PROMPT = """\
You are the presiding judge of a council of financial analyst agents. Each agent \
independently scored a news article from -5 (strong sell) to +5 (strong buy) and gave \
its reasoning. You are given the full debate transcript plus the arithmetic consensus \
computed from the agents' scores.

Do not just repeat the arithmetic mean. Read every agent's reasoning, work out why \
they disagree, weigh whose argument is stronger, and hand down your own verdict. Your \
score may match or contradict the arithmetic mean — say why in the rationale."""

JUDGE_USER_PROMPT = """\
Return a single JSON object with your ruling. No markdown, no explanation outside the JSON.

SCHEMA (follow exactly):
{schema}

DEBATE TRANSCRIPT:
{transcript}

ARITHMETIC CONSENSUS (computed from the agents' scores, not your input):
  consensus_score_raw: {consensus_score_raw}
  agreement_level: {agreement_level}
  dissenting_agents: {dissenting_agents}
{lessons_section}"""


@dataclass
class JudgeVerdict:
    """The judge's own ruling after reading the full debate."""

    verdict: str
    signal_score: int
    confidence: float
    rationale: str = ""

    def __post_init__(self):
        self.signal_score = max(-5, min(5, int(self.signal_score)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.verdict not in ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT"):
            self.verdict = AgentVerdict._verdict_from_score(self.signal_score)

    def to_dict(self) -> dict:
        return asdict(self)


def format_lessons_block(lessons: dict[str, Any] | None) -> str:
    """Render grounded past-call stats as a LESSONS block.

    Empty/falsy input returns "" so the judge prompt is byte-identical to one
    built without lessons — no lessons, no block.

    ponytail: grounded stats, not natural-language reflection — upgrade path
    is one LLM call over wrong_calls below if the stats prove too blunt.
    """
    if not lessons:
        return ""

    lines = ["LESSONS (grounded stats from past calls — the debators never see this):"]

    for ticker, stats in (lessons.get("tickers") or {}).items():
        lines.append(
            f"- {ticker}: {stats['correct']}/{stats['total']} correct "
            f"({stats['hit_rate_pct']}% hit rate)"
        )
    for source, stats in (lessons.get("sources") or {}).items():
        lines.append(
            f"- source {source}: {stats['correct']}/{stats['total']} correct "
            f"({stats['hit_rate_pct']}% hit rate)"
        )

    avg_move = lessons.get("avg_realized_move_pct")
    if avg_move is not None:
        lines.append(f"- avg realized move: {avg_move}%")

    wrong_calls = lessons.get("wrong_calls") or []
    if wrong_calls:
        lines.append("- recent wrong calls:")
        for call in wrong_calls:
            lines.append(
                f"  - {call['ticker']} {call['verdict']} -> actual "
                f"{call['price_change_pct']}% ({call['source'] or 'unknown source'}, "
                f"{call['event_type']})"
            )

    return "\n".join(lines)


def _render_transcript(verdicts: list[AgentVerdict]) -> str:
    lines = []
    for v in verdicts:
        status = " [FAILED]" if v.error else (" [NUMBER CONFLICT]" if v.number_conflict else "")
        lines.append(
            f"- {v.agent_name}{status}: verdict={v.verdict} score={v.signal_score} "
            f"confidence={v.confidence:.2f}\n  reasoning: {v.reasoning}"
        )
    return "\n".join(lines)


def judge_debate(
    transcript: list[AgentVerdict],
    stats: dict,
    lessons: dict[str, Any] | None = None,
) -> JudgeVerdict | None:
    """
    Read the whole debate transcript plus the arithmetic consensus stats and
    return an independent JudgeVerdict, or None if the judge LLM is dead —
    callers must fall back to the arithmetic consensus unchanged in that case.

    stats must carry consensus_score_raw, agreement_level, dissenting_agents.

    `lessons` (grounded past-call stats) is folded in as a LESSONS
    block — grounded past hit rate / wrong calls the debators never see.
    Only the judge carries this; empty lessons add nothing to the prompt.
    """
    lessons_block = format_lessons_block(lessons)
    prompt = JUDGE_USER_PROMPT.format(
        schema=JUDGE_RESPONSE_SCHEMA,
        transcript=_render_transcript(transcript),
        consensus_score_raw=stats.get("consensus_score_raw"),
        agreement_level=stats.get("agreement_level"),
        dissenting_agents=stats.get("dissenting_agents"),
        lessons_section=f"\n{lessons_block}\n" if lessons_block else "",
    )

    model = os.getenv(JUDGE_MODEL_ENV) or None
    raw = call_ai(prompt, JUDGE_SYSTEM_PROMPT, model=model)

    if raw is None:
        logger.warning("[Judge] AI call returned None — falling back to arithmetic consensus")
        return None

    try:
        return JudgeVerdict(
            verdict=raw.get("verdict", "CAUTIOUS"),
            signal_score=raw.get("signal_score", 0),
            confidence=raw.get("confidence", 0.5),
            rationale=raw.get("rationale", ""),
        )
    except Exception as e:
        logger.error("[Judge] Failed to parse response: %s", e)
        return None
