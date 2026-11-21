"""
Accuracy metrics shared by the backtest (server.accuracy): confidence calibration
and equity-curve risk metrics over scored verdicts.
"""

from __future__ import annotations

import math
from typing import Any

# z for a two-sided 95% interval.
Z95 = 1.959963984540054
# Below this many scored calls an interval is too wide to quote as a rate on its own, and
# a half-width above HALF_WIDTH_WIDE says the same thing in interval terms.
N_THIN = 30
HALF_WIDTH_WIDE = 0.15


def wilson_interval(hits: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for a hit rate — never below 0 or above 1, and it does
    not collapse to a point at n=0 or on an all-hit streak the way the normal
    approximation does."""
    if n <= 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def sample_note(hits: int, n: int) -> str:
    """The honest one-liner for a rate: the sample size and the interval, or why not.

    The product sells a track record, so a bare percentage has to say how many calls it
    came from (plan m1.4.1).
    """
    if n <= 0:
        return "n=0, no scored calls yet"
    ci = wilson_interval(hits, n)
    if ci is None:  # unreachable for n > 0; keeps the return type honest
        return f"n={n}"
    lo, hi = (round(x * 100) for x in ci)
    thin = " · wide interval" if (n < N_THIN or (ci[1] - ci[0]) / 2 > HALF_WIDTH_WIDE) else ""
    return f"n={n}, {lo}–{hi}%{thin}"


def calibration(rows: list[dict]) -> dict[str, Any]:
    """Brier score, its Murphy decomposition, and the reliability curve.

    rows: dicts with 'confidence' (0..1) and 'correct' (bool). Rows missing either key
    are skipped, so "no outcomes yet" reads as `n: 0`, never as a perfect score.

    The decomposition groups by distinct stated confidence rather than by bucket, so
    `reliability - resolution + uncertainty` equals the Brier score exactly; bucketed
    versions of it are only an approximation (they drop within-bucket variance).
    """
    scored = [r for r in rows if r.get("confidence") is not None and r.get("correct") is not None]
    names = ("0-.25", ".25-.5", ".5-.75", ".75-1")
    hits = {n: [] for n in names}
    for r in scored:
        hits[names[min(3, int(r["confidence"] * 4))]].append(bool(r["correct"]))
    buckets = {
        n: {
            "n": len(h),
            "hit_rate": round(sum(h) / len(h), 3) if h else None,
            "ci95": wilson_interval(sum(h), len(h)),
        }
        for n, h in hits.items()
    }
    if not scored:
        return {
            "n": 0,
            "brier": None,
            "brier_decomposition": None,
            "base_rate": None,
            "reliability_curve": [],
            "buckets": buckets,
        }

    total = len(scored)
    brier = sum((r["confidence"] - (1.0 if r["correct"] else 0.0)) ** 2 for r in scored) / total

    # Reliability curve: mean stated confidence against realised hit rate per bucket.
    curve = []
    for name in names:
        members = [r for r in scored if names[min(3, int(r["confidence"] * 4))] == name]
        if not members:
            continue
        predicted = round(sum(r["confidence"] for r in members) / len(members), 3)
        realised = round(sum(1 for r in members if r["correct"]) / len(members), 3)
        curve.append(
            {
                "bucket": name,
                "n": len(members),
                "predicted": predicted,
                "realised": realised,
                "gap": round(predicted - realised, 3),
            }
        )

    # Murphy decomposition over distinct confidence values (exact, see docstring).
    groups: dict[float, list[bool]] = {}
    for r in scored:
        groups.setdefault(round(float(r["confidence"]), 3), []).append(bool(r["correct"]))
    base = sum(1 for r in scored if r["correct"]) / total
    reliability = sum(
        len(v) / total * (f - sum(v) / len(v)) ** 2 for f, v in groups.items()
    )
    resolution = sum(len(v) / total * (sum(v) / len(v) - base) ** 2 for v in groups.values())
    uncertainty = base * (1 - base)

    return {
        "n": total,
        "brier": round(brier, 4),
        "brier_decomposition": {
            "reliability": round(reliability, 4),
            "resolution": round(resolution, 4),
            "uncertainty": round(uncertainty, 4),
        },
        "base_rate": round(base, 3),
        "reliability_curve": curve,
        "buckets": buckets,
    }


def equity_metrics(returns: list[float]) -> dict:
    """Sharpe / Sortino / max drawdown for a per-period returns series.

    Computed in pure python: the empyrical library this used to prefer is not vendored
    (`finscrape/absorbed/` does not exist in this tree), so the import always raised and the
    builtin path below was the only one that ever ran. `engine` stays in the payload because
    API clients read it.
    """
    clean = [float(r) for r in returns if r is not None]
    if not clean:
        return {"sharpe_ratio": 0.0, "sortino_ratio": 0.0, "max_drawdown": 0.0, "engine": "none"}

    engine = "builtin"
    mean = sum(clean) / len(clean)
    std = (sum((r - mean) ** 2 for r in clean) / len(clean)) ** 0.5
    downside = [min(0.0, r) for r in clean]
    downside_std = (sum(d**2 for d in downside) / len(clean)) ** 0.5
    sharpe = mean / std if std > 0 else 0.0
    sortino = mean / downside_std if downside_std > 0 else 0.0
    cum, peak, max_drawdown = 1.0, 1.0, 0.0
    for r in clean:
        cum *= 1.0 + r
        peak = max(peak, cum)
        if peak > 0:
            max_drawdown = min(max_drawdown, cum / peak - 1.0)

    def _f(value: float) -> float:
        # NaN/inf (zero-variance series) must not reach JSON responses
        return round(float(value), 4) if math.isfinite(value) else 0.0

    return {
        "sharpe_ratio": _f(sharpe),
        "sortino_ratio": _f(sortino),
        "max_drawdown": _f(max_drawdown),
        "engine": engine,
    }
