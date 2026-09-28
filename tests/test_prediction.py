"""CEIP engine: reliability tables + calibrated predictions (offline)."""

from finscrape.prediction import (
    brier_summary,
    predict,
    reliability_tables,
    structural_probability,
    _bucket,
)

import time


def outcomes():
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return [
        {"verdict": "INVEST", "outcome": "correct", "confidence": 0.8, "source": "cnbc",
         "event_type": "earnings", "checked_at": now_iso},
        {"verdict": "INVEST", "outcome": "correct", "confidence": 0.7, "source": "cnbc",
         "event_type": "earnings", "checked_at": now_iso},
        {"verdict": "PULL_OUT", "outcome": "incorrect", "confidence": 0.3, "source": "rss",
         "event_type": "geopolitical", "checked_at": now_iso},
    ]


def test_reliability_tables_compute_rates():
    tables = reliability_tables(outcomes())
    assert tables["sample_size"] == 3
    assert tables["by_verdict"]["INVEST"]["hit_rate"] == 1.0
    assert tables["by_verdict"]["PULL_OUT"]["hit_rate"] == 0.0
    assert tables["by_source"]["cnbc"]["hit_rate"] == 1.0
    assert tables["global_hit_rate"] is not None


def test_bucket_boundaries():
    assert _bucket(0.1) == "0-.25"
    assert _bucket(0.3) == ".25-.5"
    assert _bucket(0.6) == ".5-.75"
    assert _bucket(0.9) == ".75-1"


def test_structural_prior_direction():
    assert structural_probability("Revenue surged, profits beat estimates") > 0.5
    assert structural_probability("Company crashes, massive losses and bankruptcy") < 0.5


def test_predict_blends_and_reports():
    result = predict(
        text="Revenue surged beating estimates",
        verdict="INVEST", confidence=0.8, source="cnbc", event_type="earnings",
        outcomes=outcomes(),
    )
    # INVEST on cnbc/earnings went 2-for-2 → empirical layer lifts p above prior
    assert result["p_verdict_correct"] > 0.5
    assert result["data_tier"] == "thin-data"  # 3 outcomes are no track record
    assert result["factors"]["verdict"] == 1.0
    # PULL_OUT flips the axis: same market direction, opposite verdict framing
    bear = predict(
        text="Company crashes with massive losses",
        verdict="PULL_OUT", confidence=0.7, source="cnbc", event_type="earnings",
        outcomes=outcomes(),
    )
    assert 0 < bear["p_verdict_correct"] < 1


def test_predict_without_outcomes_uses_structural():
    result = predict("Neutral market note", "OBSERVE", 0.4, "rss", "other", [])
    assert result["data_tier"] == "no-outcomes"
    assert result["empirical_share"] == 0.0


def test_reliable_pull_out_points_down():
    """Hit rates say whether a verdict landed, not which way prices went: a PULL_OUT
    that is always right must read as a likely fall."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    record = [
        {"verdict": "PULL_OUT", "outcome": "correct", "confidence": 0.7, "source": "rss",
         "event_type": "geopolitical", "checked_at": now_iso}
    ] * 5
    bear = predict("Strait closed to tankers", "PULL_OUT", 0.7, "rss", "geopolitical", record)
    assert bear["p_positive_move"] < 0.5
    assert bear["p_verdict_correct"] > 0.5
    # Non-directional verdicts were never scored, so the record says nothing about them.
    watch = predict("Strait closed to tankers", "CAUTIOUS", 0.7, "rss", "geopolitical", record)
    assert watch["p_positive_move"] == watch["structural_prior"]


def test_brier_summary():
    b = brier_summary(outcomes())
    assert b["n"] == 3 and 0 <= b["brier"] <= 1


def test_empirical_tier_needs_a_real_sample():
    many = outcomes() * 10
    assert predict("Revenue surged", "INVEST", 0.8, "cnbc", "earnings", many)[
        "data_tier"
    ] == "empirical"
    assert predict("Revenue surged", "INVEST", 0.8, "cnbc", "earnings", many[:13])[
        "data_tier"
    ] == "thin-data"
