"""Calibrated Event-Impact Probability (CEIP) engine.

The differentiator: news terminals tell you what happened; prediction markets
tell you odds of events. WorldFin tells you the **calibrated probability that a
signal's direction realizes in price** — with the reliability evidence attached.

How it works (honest, small-sample aware):
- Empirical layer: reliability tables built from scored outcomes — P(hit)
  per verdict, per confidence bucket, per source, per event_type, with
  exponential recency decay. Sample sizes are tracked and surfaced.
- Structural layer: the finance-lexicon sentiment score of the event text
  (services.sentiment_analyzer) mapped through a logistic prior.
- Blend: geometric-style pooling of the two probabilities, weighted by how
  much empirical data exists (thin data → structural prior dominates).
- Every prediction carries `sample_size`, `reliability_tier` and the factor
  breakdown, so a user can audit WHY the number is what it is.

Pure functions; no I/O.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

_DECAY_HALF_LIFE_DAYS = 45.0  # outcomes older than this matter less
_CONF_BUCKETS = ("0-.25", ".25-.5", ".5-.75", ".75-1")


def _bucket(confidence: float) -> str:
    if confidence < 0.25:
        return _CONF_BUCKETS[0]
    if confidence < 0.5:
        return _CONF_BUCKETS[1]
    if confidence < 0.75:
        return _CONF_BUCKETS[2]
    return _CONF_BUCKETS[3]


def _recency_weight(checked_at: str | None, now: datetime | None = None) -> float:
    """Exponential recency decay; undated outcomes get 0.5."""
    now = now or datetime.now(UTC)
    if not checked_at:
        return 0.5
    try:
        then = datetime.fromisoformat(str(checked_at))
        if then.tzinfo is None:
            then = then.replace(tzinfo=UTC)
        age_days = max(0.0, (now - then).total_seconds() / 86400)
        return math.pow(0.5, age_days / _DECAY_HALF_LIFE_DAYS)
    except ValueError:
        return 0.5


def reliability_tables(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Empirical hit-rate tables with recency weighting.

    Returns per-verdict, per-confidence-bucket, per-source, per-event_type
    hit-rates plus the global rate and total weight.
    """
    tables: dict[str, dict[str, dict[str, float]]] = {
        "by_verdict": {}, "by_confidence": {}, "by_source": {}, "by_event_type": {},
    }
    total_w = 0.0
    total_hits = 0.0

    def _add(table: str, key: str, hit: bool, weight: float) -> None:
        cell = tables[table].setdefault(key, {"w": 0.0, "hits": 0.0})
        cell["w"] += weight
        cell["hits"] += weight if hit else 0.0

    for o in outcomes:
        hit = o.get("outcome") == "correct"
        weight = _recency_weight(o.get("checked_at"))
        total_w += weight
        total_hits += weight if hit else 0.0
        _add("by_verdict", o.get("verdict") or "?", hit, weight)
        _add("by_confidence", _bucket(float(o.get("confidence") or 0)), hit, weight)
        source = (o.get("source") or "unknown").split("/")[0]
        _add("by_source", source, hit, weight)
        _add("by_event_type", o.get("event_type") or "other", hit, weight)

    def _rates(table: dict) -> dict:
        return {
            k: {
                "hit_rate": round(v["hits"] / v["w"], 3) if v["w"] else None,
                "weight": round(v["w"], 2),
            }
            for k, v in table.items()
        }

    return {
        "global_hit_rate": round(total_hits / total_w, 3) if total_w else None,
        "total_weight": round(total_w, 2),
        "sample_size": len(outcomes),
        **{name: _rates(table) for name, table in tables.items()},
    }


def structural_probability(text: str) -> float:
    """P(directional move is positive) from the finance-lexicon engine.

    A logistic on the sentiment score: score 0 → ~0.5, |score| 1 → ~0.88.
    """
    from finscrape.services.sentiment_analyzer import SentimentAnalyzer

    score = SentimentAnalyzer.analyze_text(text).score  # -1..1
    return 1.0 / (1.0 + math.exp(-2.2 * score))


# Recency-weighted outcomes needed before a call is labelled empirical; below it the
# hit rates still blend in, but a handful of results is not a track record.
MIN_EMPIRICAL_WEIGHT = 30.0


def _empirical_p(hit_rate: float | None, weight: float, prior: float = 0.5) -> float | None:
    """Empirical hit-rate shrunk toward the prior by evidence weight."""
    if hit_rate is None:
        return None
    k = weight / (weight + 8.0)  # 8 = pseudo-count strength
    return prior * (1 - k) + hit_rate * k


def predict(text: str, verdict: str, confidence: float, source: str,
            event_type: str, outcomes: list[dict[str, Any]],
            tables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Calibrated probability the signal's direction realizes in price.

    Blends the empirical reliability of *this kind of signal* (shrunk toward
    the global base rate by sample size) with the structural sentiment prior,
    weighted by how much empirical evidence exists at all.

    `tables` lets a caller scoring many signals against one outcome set build
    the reliability tables once; it must be `reliability_tables(outcomes)`.
    """
    if tables is None:
        tables = reliability_tables(outcomes)
    empirical_total = tables["total_weight"]

    global_rate = tables["global_hit_rate"] or 0.5
    by_verdict = tables["by_verdict"].get(verdict, {})
    by_source = tables["by_source"].get(source.split("/")[0], {})
    by_type = tables["by_event_type"].get(event_type, {})

    # Pool the empirical estimates that have data (shrink each toward global).
    estimates = []
    for rate, weight in (
        (_empirical_p(by_verdict.get("hit_rate"), by_verdict.get("weight", 0), global_rate), by_verdict.get("weight", 0)),
        (_empirical_p(by_source.get("hit_rate"), by_source.get("weight", 0), global_rate), by_source.get("weight", 0)),
        (_empirical_p(by_type.get("hit_rate"), by_type.get("weight", 0), global_rate), by_type.get("weight", 0)),
    ):
        if rate is not None and weight > 0:
            estimates.append((rate, weight))

    structural = structural_probability(text)
    verdict_up = verdict in ("INVEST",)
    # A hit rate is P(verdict landed); only a directional verdict turns it into
    # P(up), and a PULL_OUT that lands means prices fell.
    if estimates and verdict in ("INVEST", "PULL_OUT"):
        wsum = sum(w for _, w in estimates)
        empirical_p = sum(r * w for r, w in estimates) / wsum
        empirical_up = empirical_p if verdict_up else 1 - empirical_p
        empirical_share = min(0.75, wsum / (wsum + 6.0))
        p_positive = empirical_up * empirical_share + structural * (1 - empirical_share)
        data_tier = "empirical" if empirical_total >= MIN_EMPIRICAL_WEIGHT else "thin-data"
    else:
        p_positive = structural
        empirical_share = 0.0
        data_tier = "no-outcomes"

    # Directional consistency: if the verdict is PULL_OUT, price "realizing"
    # means downside — flip the probability onto the verdict's own axis.
    p_verdict_right = p_positive if verdict_up else (1 - p_positive)

    confidence_band = round(0.5 + 0.4 * min(1.0, abs(p_verdict_right - 0.5) * 2), 3)

    return {
        "p_positive_move": round(p_positive, 3),
        "p_verdict_correct": round(p_verdict_right, 3),
        "expected_direction": "up" if p_positive >= 0.5 else "down",
        "confidence_band": confidence_band,
        "structural_prior": round(structural, 3),
        "empirical_share": round(empirical_share, 2),
        "data_tier": data_tier,
        "factors": {
            "verdict": by_verdict.get("hit_rate"),
            "source": by_source.get("hit_rate"),
            "event_type": by_type.get("hit_rate"),
            "global_base_rate": tables["global_hit_rate"],
        },
        "reliability_tables": tables,
    }


def brier_summary(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Brier score of recorded confidences vs realized correctness."""
    scored = [o for o in outcomes if o.get("confidence") is not None and o.get("outcome") in ("correct", "incorrect")]
    if not scored:
        return {"brier": None, "n": 0}
    brier = sum(
        ((float(o["confidence"]) - (1.0 if o["outcome"] == "correct" else 0.0)) ** 2)
        for o in scored
    ) / len(scored)
    return {"brier": round(brier, 4), "n": len(scored)}
