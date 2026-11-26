"""The ablation table must be the shipped rule, or it measures nothing (plan M5.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from finscrape.analysis.validator import _MAGNITUDE_CAP, calibrate_signal_score
from scripts import ablation

ROOT = Path(__file__).resolve().parent.parent
RECORDING = ROOT / "tests" / "gold" / "recordings" / "keyword-baseline.jsonl"


def test_shipped_table_matches_validator() -> None:
    assert ablation.MAGNITUDE_CAP == _MAGNITUDE_CAP


def test_both_toggles_on_equals_the_shipped_rule_on_the_recording() -> None:
    replies = ablation.load_replies(RECORDING)
    assert len(replies) == 243
    for reply in replies:
        assert ablation.variant(
            reply.get("signal_score", 0),
            reply.get("magnitude"),
            reply.get("actionability"),
            reply.get("novelty"),
        ) == calibrate_signal_score(
            reply.get("signal_score", 0),
            reply.get("magnitude") or "medium",
            reply.get("actionability") or "medium",
            reply.get("novelty") or "standard",
        )


@pytest.mark.parametrize("score", list(range(-5, 6)))
@pytest.mark.parametrize("magnitude", ["low", "medium", "high", None])
@pytest.mark.parametrize("actionability", ["low", "medium", "high", None])
@pytest.mark.parametrize("novelty", ["breaking", "standard", "follow_up", "rehash", None])
def test_both_toggles_on_equals_the_shipped_rule_on_the_grid(
    score: int, magnitude: str | None, actionability: str | None, novelty: str | None
) -> None:
    assert ablation.variant(score, magnitude, actionability, novelty) == (
        calibrate_signal_score(
            score,
            magnitude or "medium",
            actionability or "medium",
            novelty or "standard",
        )
    )


def test_magnitude_cap_moves_a_low_magnitude_call() -> None:
    # low magnitude caps at 2; with the cap off the same call stays at 4.
    assert ablation.variant(-4, "low", "medium", "standard") == -2
    assert ablation.variant(-4, "low", "medium", "standard", cap=False) == -4


def test_novelty_rescale_moves_a_rehash() -> None:
    # a rehash is held at 2; with the rescale off the high magnitude cap of 5 applies.
    assert ablation.variant(4, "high", "high", "rehash") == 2
    assert ablation.variant(4, "high", "high", "rehash", novelty_rescale=False) == 4


def test_zero_stays_zero_under_every_toggle() -> None:
    for cap in (True, False):
        for novelty_rescale in (True, False):
            assert (
                ablation.variant(
                    0, "high", "high", "rehash", cap=cap, novelty_rescale=novelty_rescale
                )
                == 0
            )


def test_verdict_bands_come_from_the_eval_harness() -> None:
    from scripts.eval_model import _verdict_from_score

    assert ablation.verdicts([3, 0, -1, -3]) == ["INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT"]
    assert ablation.verdicts([3, 0, -1, -3]) == [
        _verdict_from_score({"signal_score": s}) for s in (3, 0, -1, -3)
    ]


def test_report_publishes_four_arms_with_deltas() -> None:
    rows = ablation.report(ablation.load_replies(RECORDING))
    assert [r["arm"] for r in rows] == [
        "cap on x novelty on",
        "cap off x novelty on",
        "cap on x novelty off",
        "cap off x novelty off",
    ]
    shipped = rows[0]
    assert shipped["verdict_delta"] == 0 and shipped["score_changes"] == 0
    assert sum(shipped["counts"].values()) == 243
    for row in rows:
        assert row["verdict_delta"] >= 0
        assert sum(row["counts"].values()) == 243


def test_main_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert ablation.main(["--recording", str(RECORDING)]) == 0
    out = capsys.readouterr().out
    assert "cap on x novelty on" in out
    assert "cap off x novelty off" in out
    assert "cases           243" in out
    assert out.count("x novelty") >= 4
