"""Pick NEUTRAL_SCALE for finscrape.analysis.laya: the neutral discount that maximises
balanced direction recall on one half of the holdout, reported on the other half.

    .venv/Scripts/python scripts/laya_train/tune_neutral.py [MODEL_DIR]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily as d

from finscrape.analysis import laya

GRID = [round(0.1 * i, 1) for i in range(2, 11)]


def recall(rows: list[tuple[str, dict]], scale: float) -> float:
    laya.NEUTRAL_SCALE = scale
    return d.balanced_recall(
        [(t, laya._pick(laya._discount_neutral(a))[0]) for t, a in rows]
    )


def main() -> None:
    model = Path(sys.argv[1]) if len(sys.argv) > 1 else d.CURRENT
    d.use_model(model if model.exists() else None)
    cases = [c for c in d.load(d.DATA / "holdout.json") if c.get("direction")]
    rows = []
    for c in cases:
        out = laya._predict(c["subject"], {"direction": laya._QUESTIONS["direction"]})
        rows.append((c["direction"], out["answers"]["direction"]))
    random.Random(d.MIN_GAIN).shuffle(rows)
    fit, check = rows[::2], rows[1::2]
    best = max(GRID, key=lambda s: recall(fit, s))
    print(f"{model.name}: {len(rows)} cases")
    for s in GRID:
        print(f"  scale {s}: fit {recall(fit, s):.3f}  check {recall(check, s):.3f}")
    print(
        f"best {best}: check half {recall(check, 1.0):.3f} -> {recall(check, best):.3f}"
    )


if __name__ == "__main__":
    main()
