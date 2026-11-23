"""Calibration as measurement, not a bare percentage (plan m1.4.1).

The product sells a "calibrated probability", so the numbers have to survive a statistician:
the Brier score decomposes exactly into reliability, resolution and uncertainty; every rate
carries an n and a Wilson interval; and too-small samples say so instead of pretending.
"""

from __future__ import annotations

import pytest

from finscrape.signals.accuracy import calibration, sample_note, wilson_interval


def test_wilson_interval_matches_the_textbook_example():
    # 50/100: the canonical 95% Wilson interval is 0.404 – 0.596.
    lo, hi = wilson_interval(50, 100)
    assert (lo, hi) == (0.404, 0.596)


def test_wilson_interval_stays_inside_zero_and_one_at_the_edges():
    assert wilson_interval(0, 10) == (0.0, 0.278), "never leaks a negative bound"
    assert wilson_interval(10, 10) == (0.722, 1.0), "never leaks above 1"
    assert wilson_interval(0, 0) is None, "no calls is not a rate"


def test_sample_note_states_n_and_calls_a_thin_sample_thin():
    assert sample_note(0, 0) == "n=0, no scored calls yet"
    assert sample_note(50, 100) == "n=100, 40–60%"
    assert "wide interval" in sample_note(2, 3), "three calls cannot support a rate"
    assert "wide interval" in sample_note(5, 12)
    assert "wide interval" not in sample_note(60, 100)


def test_brier_decomposition_reproduces_the_brier_score():
    rows = (
        [{"confidence": 0.9, "correct": True} for _ in range(18)]
        + [{"confidence": 0.9, "correct": False} for _ in range(2)]
        + [{"confidence": 0.6, "correct": True} for _ in range(6)]
        + [{"confidence": 0.6, "correct": False} for _ in range(14)]
        + [{"confidence": 0.3, "correct": True} for _ in range(4)]
        + [{"confidence": 0.3, "correct": False} for _ in range(16)]
    )
    calib = calibration(rows)
    parts = calib["brier_decomposition"]

    assert calib["brier"] == pytest.approx(
        parts["reliability"] - parts["resolution"] + parts["uncertainty"], abs=1e-4
    )
    # A model that says 0.6 and hits 0.3 is miscalibrated upward: reliability is the part
    # of the Brier score that is the model's own fault, resolution the part its calls earn.
    assert parts["reliability"] == pytest.approx(0.0333, abs=1e-4)
    assert parts["resolution"] > 0.05
    # 28 of 60 calls came true, so the base rate alone predicts an uncertainty of
    # p(1-p) — the score a model that always says "47%" would earn.
    assert calib["base_rate"] == pytest.approx(28 / 60, abs=1e-3)
    assert parts["uncertainty"] == pytest.approx((28 / 60) * (1 - 28 / 60), abs=1e-3)


def test_the_reliability_curve_reports_predicted_against_realised():
    rows = [{"confidence": 0.9, "correct": True} for _ in range(8)]
    rows += [{"confidence": 0.9, "correct": False} for _ in range(2)]
    curve = calibration(rows)["reliability_curve"]

    assert curve == [
        {"bucket": ".75-1", "n": 10, "predicted": 0.9, "realised": 0.8, "gap": 0.1}
    ]


def test_no_outcomes_reports_n_zero_and_no_brier():
    calib = calibration([])

    assert calib["n"] == 0
    assert calib["brier"] is None and calib["brier_decomposition"] is None
    assert calib["base_rate"] is None
    assert calib["reliability_curve"] == []
    assert all(b["ci95"] is None for b in calib["buckets"].values())


def test_unscored_rows_are_excluded_not_scored_as_misses():
    rows = [
        {"confidence": 0.8, "correct": True},
        {"confidence": 0.8, "correct": None},
        {"confidence": None, "correct": False},
    ]
    calib = calibration(rows)

    assert calib["n"] == 1, "an open window is not a wrong call"
    assert calib["brier"] == pytest.approx(0.04, abs=1e-6)
