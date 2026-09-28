"""Scenario advice (finscrape.scenarios).

`predict_fn` is injected everywhere, so these run without Postgres, Ollama or the
sentiment lexicon: the tests pin the aggregation, not the probability engine.
"""

from __future__ import annotations

from typing import Any

import pytest

from finscrape.scenarios import build_scenarios, event_weight, score_scenario


def fake_predict(p_positive: float, tier: str = "empirical"):
    """A predict_fn that always returns the same probability."""

    def _predict(**_kwargs: Any) -> dict[str, Any]:
        return {"p_positive_move": p_positive, "data_tier": tier}

    return _predict


def by_subject(mapping: dict[str, float]):
    """A predict_fn keyed on the text it is handed, for mixed clusters."""

    def _predict(**kwargs: Any) -> dict[str, Any]:
        text = kwargs["text"]
        for needle, value in mapping.items():
            if needle in text:
                return {"p_positive_move": value, "data_tier": "empirical"}
        return {"p_positive_move": 0.5, "data_tier": "no-outcomes"}

    return _predict


def event(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": 1,
        "subject": "Strait closed to tankers",
        "reasoning": "",
        "verdict": "PULL_OUT",
        "confidence": 0.8,
        "event_type": "geopolitical",
        "magnitude": "high",
        "novelty": "breaking",
        "actionability": "high",
        "sector_impact": "energy/transport",
        "tickers": ["XOM"],
        "sources": ["reuters/world"],
        "affected_entities": [],
        "second_order_effects": [],
        "divergence_flag": False,
        "created_at": "2026-09-20T00:00:00",
    }
    base.update(overrides)
    return base


def cluster(*members: dict[str, Any], **meta: Any) -> dict[str, Any]:
    base = {
        "members": list(members),
        "top_subject": members[0]["subject"] if members else "",
        "sources": ["reuters/world"],
        "first_seen": "2026-09-20T00:00:00",
    }
    base.update(meta)
    return base


class TestEventWeight:
    def test_grades_multiply(self) -> None:
        loud = event_weight(
            event(confidence=1.0, magnitude="critical", actionability="high")
        )
        quiet = event_weight(
            event(confidence=1.0, magnitude="low", actionability="low")
        )
        assert loud > quiet

    def test_confidence_scales_the_whole_weight(self) -> None:
        assert event_weight(event(confidence=0.5)) == pytest.approx(
            event_weight(event(confidence=1.0)) * 0.5
        )

    def test_a_zero_confidence_member_still_counts(self) -> None:
        assert event_weight(event(confidence=0.0)) > 0

    def test_unknown_grades_fall_back_to_medium(self) -> None:
        assert event_weight(
            event(magnitude="???", actionability=None)
        ) == pytest.approx(
            event_weight(event(magnitude="medium", actionability="medium"))
        )

    def test_a_junk_confidence_does_not_raise(self) -> None:
        assert event_weight(event(confidence="n/a")) > 0


class TestScoreScenario:
    def test_an_empty_cluster_scores_nothing(self) -> None:
        assert score_scenario(cluster(), [], fake_predict(0.9)) is None

    def test_a_bullish_cluster_is_risk_on(self) -> None:
        out = score_scenario(cluster(event()), [], fake_predict(0.8))
        assert out is not None
        assert out["stance"] == "risk-on"
        assert out["direction"] == "up"
        assert out["probability"] == pytest.approx(0.8)

    def test_a_bearish_cluster_reports_conviction_not_the_raw_probability(self) -> None:
        # p_positive 0.2 is an 80% confident call that the move is *down*.
        out = score_scenario(cluster(event()), [], fake_predict(0.2))
        assert out is not None
        assert out["stance"] == "risk-off"
        assert out["direction"] == "down"
        assert out["probability"] == pytest.approx(0.8)

    def test_opposing_members_cancel_into_mixed(self) -> None:
        out = score_scenario(
            cluster(
                event(id=1, subject="up leg"),
                event(id=2, subject="down leg"),
            ),
            [],
            by_subject({"up leg": 0.9, "down leg": 0.1}),
        )
        assert out is not None
        assert out["stance"] == "mixed"
        assert out["advice"].startswith("Mixed signal")

    def test_a_heavier_member_wins_the_tie(self) -> None:
        out = score_scenario(
            cluster(
                event(id=1, subject="up leg", confidence=1.0, magnitude="critical"),
                event(id=2, subject="down leg", confidence=0.1, magnitude="low"),
            ),
            [],
            by_subject({"up leg": 0.9, "down leg": 0.1}),
        )
        assert out is not None
        assert out["stance"] == "risk-on"

    def test_exposure_covers_entity_tickers_the_event_did_not_list(self) -> None:
        out = score_scenario(
            cluster(
                event(
                    tickers=["XOM"],
                    affected_entities=[{"name": "Shell", "ticker": "SHEL"}],
                )
            ),
            [],
            fake_predict(0.8),
        )
        assert out is not None
        assert {leg["name"] for leg in out["exposure"]} == {"XOM", "SHEL"}

    def test_sector_impact_splits_on_any_separator(self) -> None:
        out = score_scenario(
            cluster(event(sector_impact="energy/healthcare; financials")),
            [],
            fake_predict(0.8),
        )
        assert out is not None
        assert {leg["name"] for leg in out["sectors"]} == {
            "energy",
            "healthcare",
            "financials",
        }

    def test_sector_impact_is_aliased_onto_the_taxonomy(self) -> None:
        """`transport` and `defense` are drift the LLM produces; both are
        industrials, so they must land on one leg rather than three."""
        out = score_scenario(
            cluster(event(sector_impact="energy/transport, defense")),
            [],
            fake_predict(0.8),
        )
        assert out is not None
        assert {leg["name"] for leg in out["sectors"]} == {"energy", "industrials"}

    def test_the_advice_names_both_sides(self) -> None:
        out = score_scenario(
            cluster(
                event(id=1, subject="up leg", sector_impact="energy", confidence=1.0),
                event(
                    id=2, subject="down leg", sector_impact="healthcare", confidence=0.9
                ),
            ),
            [],
            by_subject({"up leg": 0.95, "down leg": 0.05}),
        )
        assert out is not None
        assert "add energy" in out["advice"]
        assert "reduce healthcare" in out["advice"]

    def test_advice_admits_when_nothing_is_tradable(self) -> None:
        out = score_scenario(
            cluster(event(tickers=[], sector_impact="", affected_entities=[])),
            [],
            fake_predict(0.9),
        )
        assert out is not None
        assert out["advice"] == "No tradable exposure identified - monitor only."

    def test_the_second_order_chain_dedupes_across_members(self) -> None:
        out = score_scenario(
            cluster(
                event(
                    id=1, second_order_effects=["Freight rates spike", "Insurance up"]
                ),
                event(
                    id=2,
                    second_order_effects=["freight rates spike", "Refining margins up"],
                ),
            ),
            [],
            fake_predict(0.8),
        )
        assert out is not None
        assert out["chain"] == [
            "Freight rates spike",
            "Insurance up",
            "Refining margins up",
        ]

    def test_divergent_members_are_counted_not_hidden(self) -> None:
        out = score_scenario(
            cluster(event(id=1, divergence_flag=True), event(id=2)),
            [],
            fake_predict(0.8),
        )
        assert out is not None
        assert out["divergent_members"] == 1

    def test_the_id_is_stable_across_member_order(self) -> None:
        a = event(id=7)
        b = event(id=3)
        first = score_scenario(cluster(a, b), [], fake_predict(0.8))
        second = score_scenario(cluster(b, a), [], fake_predict(0.8))
        assert first is not None and second is not None
        assert first["id"] == second["id"] == "s3"


class TestBuildScenarios:
    def test_singletons_are_dropped_when_real_clusters_exist(self) -> None:
        out = build_scenarios(
            [
                cluster(event(id=1), event(id=2), top_subject="clustered"),
                cluster(event(id=3), top_subject="lone headline"),
            ],
            [],
            predict_fn=fake_predict(0.8),
        )
        assert [s["title"] for s in out] == ["clustered"]

    def test_a_quiet_day_falls_back_to_singletons_rather_than_advising_nothing(
        self,
    ) -> None:
        out = build_scenarios(
            [cluster(event(id=3), top_subject="lone headline")],
            [],
            predict_fn=fake_predict(0.8),
        )
        assert [s["title"] for s in out] == ["lone headline"]

    def test_conviction_outranks_size(self) -> None:
        out = build_scenarios(
            [
                cluster(
                    *[event(id=i, subject="weak leg") for i in range(1, 6)],
                    top_subject="big but undecided",
                ),
                cluster(
                    event(id=10, subject="strong leg"),
                    event(id=11, subject="strong leg"),
                    top_subject="small but certain",
                ),
            ],
            [],
            predict_fn=by_subject({"weak leg": 0.52, "strong leg": 0.95}),
        )
        assert [s["title"] for s in out] == ["small but certain", "big but undecided"]

    def test_the_limit_is_honoured(self) -> None:
        clusters = [
            cluster(event(id=i), event(id=i + 100), top_subject=f"s{i}")
            for i in range(1, 6)
        ]
        assert len(build_scenarios(clusters, [], fake_predict(0.8), limit=2)) == 2


def test_cancelled_exposure_is_not_reported_as_no_exposure() -> None:
    """Two members hitting the same sector in opposite directions net to zero.

    That is a flat position, not an untouched one, and the advice must say which.
    """
    out = score_scenario(
        cluster(
            event(id=1, subject="up leg", sector_impact="energy", tickers=["XOM"]),
            event(id=2, subject="down leg", sector_impact="energy", tickers=["XOM"]),
        ),
        [],
        by_subject({"up leg": 0.9, "down leg": 0.1}),
    )
    assert out is not None
    assert out["sectors"] == [] and out["exposure"] == []
    assert out["advice"] == "Mixed signal: exposure nets flat - monitor."


def test_scenario_reports_the_outcome_sample_behind_its_tier():
    def predict(**_kwargs: Any) -> dict[str, Any]:
        return {
            "p_positive_move": 0.3,
            "data_tier": "thin-data",
            "reliability_tables": {"sample_size": 13},
        }

    scenario = score_scenario({"members": [event()]}, [], predict)
    assert scenario is not None
    assert scenario["sample_size"] == 13
