"""Ablate the score-calibration rules the recorded replay can actually feed (plan M5.2).

    .venv/Scripts/python.exe -m scripts.ablation
    ... --recording tests/gold/recordings/keyword-baseline.jsonl

The live pipeline turns a model's integer into a market signal through
`finscrape.analysis.validator.score_trace` (called by `calibrate_signal_score`). Two of
its rules can be toggled on data we hold: the magnitude cap (`_MAGNITUDE_CAP`: low 2,
medium 3, high 5) and the novelty rescale (a rehash is capped at 2). This script replays
the recorded corpus under all four combinations and publishes the verdict counts and the
delta against the shipped combination.

The pipeline also clamps a direction disagreement to +-2 (`finscrape/pipeline.py`, after
calibration). That rule needs the article text to recompute `check_divergence`, and the
recording stores replies without it, so it is not an axis here. With both toggles on the
local implementation is asserted equal to `calibrate_signal_score` for every row, which is
what keeps this file from drifting away from the shipped rule.

Verdict bands are imported from `scripts.eval_model`, not copied: a change to the shipped
thresholds must move this table too.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDING = ROOT / "tests" / "gold" / "recordings" / "keyword-baseline.jsonl"

# Same table as validator._MAGNITUDE_CAP, which is not importable as a knob. The equality
# test in tests/test_ablation.py fails the moment the shipped table moves.
MAGNITUDE_CAP = {"low": 2, "medium": 3, "high": 5}
ACTIONABILITY = ("low", "medium", "high")
NOVELTY = ("breaking", "standard", "follow_up", "rehash")
VERDICTS = ("INVEST", "OBSERVE", "CAUTIOUS", "PULL_OUT")


def variant(
    score: Any,
    magnitude: str | None,
    actionability: str | None,
    novelty: str | None,
    *,
    cap: bool = True,
    novelty_rescale: bool = True,
) -> int:
    """`score_trace`, with either cap switchable off.

    cap=False drops the magnitude ceiling (a low-magnitude story may reach +-5);
    novelty_rescale=False lets a rehash keep the magnitude ceiling instead of being held
    at 2. Sign is never changed and 0 stays 0, exactly as shipped.
    """
    try:
        base = round(float(score))
    except (TypeError, ValueError):
        base = 0
    base = max(-5, min(5, base))
    if base == 0:
        return 0

    mag = magnitude if magnitude in MAGNITUDE_CAP else "medium"
    act = actionability if actionability in ACTIONABILITY else "medium"
    nov = novelty if novelty in NOVELTY else "standard"

    sign = 1 if base > 0 else -1
    strength = abs(base)
    ceiling = MAGNITUDE_CAP[mag] if cap else 5
    if novelty_rescale and nov == "rehash":
        ceiling = min(ceiling, 2)
    if strength >= 3 and nov != "rehash" and (act == "high" or nov == "breaking"):
        ceiling = min(5, ceiling + 1)
    if act == "low" and strength > 4:
        ceiling = min(ceiling, 4)
    strength = min(strength, ceiling)

    if strength <= 2 and mag == "high" and act == "high" and nov != "rehash":
        strength = 3
    if strength >= 3 and mag == "high" and act == "high" and nov == "breaking":
        strength = min(5, strength + 1)

    return sign * max(1, strength)


@dataclass(frozen=True)
class Arm:
    cap: bool
    novelty_rescale: bool

    @property
    def label(self) -> str:
        return (
            f"cap {'on' if self.cap else 'off'} x "
            f"novelty {'on' if self.novelty_rescale else 'off'}"
        )


ARMS = (
    Arm(cap=True, novelty_rescale=True),
    Arm(cap=False, novelty_rescale=True),
    Arm(cap=True, novelty_rescale=False),
    Arm(cap=False, novelty_rescale=False),
)


def load_replies(path: Path = DEFAULT_RECORDING) -> list[dict[str, Any]]:
    """The reply payloads of an eval recording, header excluded."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return []
    header = json.loads(lines[0])
    if header.get("kind") != "eval-recording":
        raise SystemExit(f"{path}: not an eval recording")
    replies = [json.loads(ln) for ln in lines[1:]]
    return [r["reply"] for r in replies if r.get("reply")]


def score_arm(replies: list[dict[str, Any]], arm: Arm) -> list[int]:
    return [
        variant(
            r.get("signal_score", 0),
            r.get("magnitude"),
            r.get("actionability"),
            r.get("novelty"),
            cap=arm.cap,
            novelty_rescale=arm.novelty_rescale,
        )
        for r in replies
    ]


def count_verdicts(scores: list[int]) -> dict[str, int]:
    counts = {v: 0 for v in VERDICTS}
    for v in verdicts(scores):
        counts[v] += 1
    return counts


def verdicts(scores: list[int]) -> list[str]:
    from scripts.eval_model import _verdict_from_score

    return [_verdict_from_score({"signal_score": s}) for s in scores]


def report(replies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per arm: verdict counts plus the delta against the shipped arm."""
    shipped_scores = score_arm(replies, ARMS[0])
    shipped_verdicts = verdicts(shipped_scores)
    rows = []
    for arm in ARMS:
        scores = score_arm(replies, arm)
        arm_verdicts = verdicts(scores)
        rows.append(
            {
                "arm": arm.label,
                "counts": count_verdicts(scores),
                "verdict_delta": sum(
                    1 for a, b in zip(arm_verdicts, shipped_verdicts, strict=True) if a != b
                ),
                "score_changes": sum(
                    1 for a, b in zip(scores, shipped_scores, strict=True) if a != b
                ),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    from finscrape.analysis.validator import calibrate_signal_score

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", default=str(DEFAULT_RECORDING))
    args = parser.parse_args(argv)
    path = Path(args.recording)
    replies = load_replies(path)

    drift = [
        i
        for i, r in enumerate(replies)
        if variant(
            r.get("signal_score", 0),
            r.get("magnitude"),
            r.get("actionability"),
            r.get("novelty"),
        )
        != calibrate_signal_score(
            r.get("signal_score", 0),
            r.get("magnitude") or "medium",
            r.get("actionability") or "medium",
            r.get("novelty") or "standard",
        )
    ]
    if drift:
        raise SystemExit(
            f"drift: {len(drift)} rows disagree with the shipped rule (first id {drift[0]})"
        )

    rows = report(replies)
    nonzero = sum(1 for r in replies if r.get("signal_score"))
    with_fields = sum(
        1
        for r in replies
        if r.get("magnitude") and r.get("actionability") and r.get("novelty")
    )
    print(f"recording       {path.name}")
    print(f"cases           {len(replies)} ({nonzero} with a non-zero score, "
          f"{with_fields} carrying all three calibration fields)")
    print(
        "arm                                  INVEST OBSERVE CAUTIOUS PULL_OUT "
        "verdict-delta score-changes"
    )
    for row in rows:
        c = row["counts"]
        print(
            f"{row['arm']:<36} {c['INVEST']:>6} {c['OBSERVE']:>7} {c['CAUTIOUS']:>8} "
            f"{c['PULL_OUT']:>8} {row['verdict_delta']:>13} {row['score_changes']:>13}"
        )
    print(
        "reading: verdict-delta counts calls whose verdict moves against the shipped arm; "
        "score-changes counts rows whose score moves."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
