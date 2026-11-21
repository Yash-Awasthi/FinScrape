"""Signal scores must track magnitude/actionability, not cluster on ±3."""

from __future__ import annotations

import pytest

from finscrape.analysis.validator import calibrate_signal_score


@pytest.mark.parametrize(
    ("score", "magnitude", "actionability", "novelty", "expected"),
    [
        # A routine low-magnitude story cannot be a ±3 call.
        (3, "low", "low", "standard", 2),
        (-3, "low", "medium", "standard", -2),
        # Medium magnitude keeps the model's ±3.
        (3, "medium", "medium", "standard", 3),
        # High magnitude + high actionability + breaking expands past ±3.
        (3, "high", "high", "breaking", 4),
        (4, "high", "high", "standard", 4),
        # A rehash is never a big new signal.
        (5, "high", "high", "rehash", 2),
        # Big but untradeable stays below the top of the scale.
        (5, "high", "low", "standard", 4),
        # Strong story the model undercalled.
        (1, "high", "high", "standard", 3),
        # Direction is preserved and out-of-range input is clamped.
        (-9, "high", "high", "breaking", -5),
        (9, "low", "low", "standard", 2),
        (0, "high", "high", "breaking", 0),
    ],
)
def test_calibration_uses_the_whole_scale(
    score, magnitude, actionability, novelty, expected
):
    assert calibrate_signal_score(score, magnitude, actionability, novelty) == expected


def test_calibration_never_flips_a_sign():
    for score in range(-5, 6):
        for magnitude in ("low", "medium", "high"):
            for action in ("low", "medium", "high"):
                for novelty in ("breaking", "standard", "follow_up", "rehash"):
                    out = calibrate_signal_score(score, magnitude, action, novelty)
                    assert (out >= 0) == (score >= 0) or score == 0
                    assert -5 <= out <= 5


def test_calibration_survives_junk_fields():
    assert calibrate_signal_score("3", "huge", "", "later") == 3
    assert calibrate_signal_score("n/a", "high", "high", "breaking") == 0
