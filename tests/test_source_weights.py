"""Source weighting: a 90-day hit rate as a small, bounded weight (M5.1).

The prior exists so a source with a bad record cannot steer a scenario on its
own. It must not become a veto, so the last test pins the volume case where it
loses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from finscrape.signals import source_weights
from finscrape.signals.scenarios import build_scenarios, event_weight

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

BAD = "badwire"
GOOD = "goodwire"


def show(capsys: Any, message: str) -> None:
    """`pytest -q` hides captured stdout; this keeps the numbers in the run."""
    with capsys.disabled():
        print(message)


def outcome(source: str, correct: bool, days_ago: float) -> dict[str, Any]:
    return {
        "source": source,
        "outcome": "correct" if correct else "incorrect",
        "checked_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def history(source: str, n: int, hits: int) -> list[dict[str, Any]]:
    """`n` recent outcomes for one source, `hits` of them correct."""
    return [outcome(source, i < hits, 1 + i * 0.5) for i in range(n)]


def cell(n: int, hits: int) -> dict[str, Any]:
    return {"n": n, "hits": hits, "rate": hits / n}


def member(member_id: int, source: str, subject: str) -> dict[str, Any]:
    """Every member carries the same event_weight: same confidence and grades."""
    return {
        "id": member_id,
        "subject": subject,
        "reasoning": "",
        "verdict": "OBSERVE",
        "confidence": 0.8,
        "event_type": "geopolitical",
        "magnitude": "high",
        "actionability": "high",
        "sector_impact": "energy",
        "tickers": ["XOM"],
        "sources": [source],
        "affected_entities": [],
        "second_order_effects": [],
        "divergence_flag": False,
    }


def up_for_prefix(prefix: str):
    def _predict(**kwargs: Any) -> dict[str, Any]:
        up = str(kwargs["text"]).startswith(prefix)
        return {"p_positive_move": 0.9 if up else 0.1, "data_tier": "empirical"}

    return _predict


def score(members: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = history(BAD, 100, 10) + history(GOOD, 100, 90)
    cluster = {"members": members, "reports": len(members), "top_subject": "mixed"}
    scenarios = build_scenarios(
        [cluster], outcomes, predict_fn=up_for_prefix("up"), min_size=1
    )
    return scenarios[0]


def describe(scenario: dict[str, Any]) -> str:
    return (
        f"priors={scenario['source_priors']} tilt={scenario['tilt']} "
        f"probability={scenario['probability']} direction={scenario['direction']}"
    )


def test_the_window_counts_only_rows_inside_90_days() -> None:
    rows = [
        outcome("wire", True, 10),
        outcome("wire", False, 89),
        outcome("wire", True, 91),
        outcome("wire", True, 200),
    ]
    stats = source_weights.hit_rates(rows, now=NOW)
    assert stats["wire"]["n"] == 2
    assert stats["wire"]["hits"] == 1
    assert stats["wire"]["rate"] == 0.5


def test_the_prior_stays_inside_its_declared_bounds(capsys: Any) -> None:
    lo, hi = source_weights.PRIOR_MIN, source_weights.PRIOR_MAX
    worst = source_weights.prior(cell(100, 0))
    best = source_weights.prior(cell(100, 100))
    show(
        capsys,
        f"bounds: prior(0% n=100)={worst} prior(100% n=100)={best} declared=[{lo}, {hi}]",
    )
    show(
        capsys,
        f"bounds: prior(10% n=50)={source_weights.prior(cell(50, 5))} "
        f"prior(90% n=50)={source_weights.prior(cell(50, 45))}",
    )
    assert lo <= worst <= hi
    assert lo <= best <= hi
    assert worst < 1.0 < best


def test_thin_data_does_not_move_the_weight() -> None:
    assert source_weights.prior(cell(9, 0)) == 1.0
    assert source_weights.prior({"n": 0, "hits": 0, "rate": 0.0}) == 1.0
    assert source_weights.prior(None) == 1.0


def test_a_historically_wrong_source_cannot_outvote_a_right_one(capsys: Any) -> None:
    members = [member(1, BAD, "up: bad source"), member(2, GOOD, "down: good source")]
    assert len({event_weight(m) for m in members}) == 1
    scenario = score(members)
    show(capsys, "1v1: " + describe(scenario))
    assert scenario["source_priors"] == {BAD: 0.85, GOOD: 1.15}
    assert scenario["direction"] == "down"


def test_a_60_percent_source_only_gets_a_nudge(capsys: Any) -> None:
    """A 60%-hit record at n=100 must stay within 6% of neutral."""
    nudge = source_weights.prior(cell(100, 60))
    show(capsys, f"nudge: prior(60% n=100)={nudge}")
    assert 0.94 <= nudge <= 1.06


def test_a_small_prior_is_not_a_veto(capsys: Any) -> None:
    """Five members from a 10%-hit source still outvote one from a 90%-hit source."""
    members = [member(i, BAD, f"up: bad {i}") for i in (1, 2, 3, 4, 5)]
    members.append(member(6, GOOD, "down: good 6"))
    assert len({event_weight(m) for m in members}) == 1
    scenario = score(members)
    show(capsys, "5v1: " + describe(scenario))
    assert scenario["direction"] == "up"
