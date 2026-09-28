"""Scenario advice: what a cluster of related events implies for a book.

A scenario is a storyline (`finscrape.analysis.clusters`) scored as one thing —
how likely its direction realizes, which tickers and sectors it touches, which
way, and one plain instruction. The probability comes from the same calibrated
engine as single-event prediction (`finscrape.prediction.predict`), so a
scenario can never disagree with the events inside it.

Pure: `build_scenarios` takes the clusters, the outcome rows and a `predict_fn`
seam, so tests run without Postgres, Ollama or a network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from finscrape.analysis.sectors import normalize as normalize_sectors

# How much one member steers its scenario. An event graded high-magnitude and
# high-actionability moves the advice more than a footnote does, and low
# confidence shrinks both.
_MAGNITUDE_WEIGHT = {"low": 0.5, "medium": 1.0, "high": 1.6, "critical": 2.2}
_ACTIONABILITY_WEIGHT = {"low": 0.4, "medium": 1.0, "high": 1.7}

_MIN_WEIGHT = 0.05  # a zero-confidence member still counts, barely

# Worst-to-best evidence tiers as `finscrape.prediction.predict` names them.
_TIER_RANK = {"no-outcomes": 0, "thin-data": 1, "empirical": 2}

# Below this tilt the two sides cancel and the honest answer is "mixed".
_MIXED_BAND = 0.08

_MAX_EXPOSURE = 8
_MAX_SECTORS = 5
_MAX_CHAIN = 6


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def event_weight(event: dict[str, Any]) -> float:
    """Steering weight of one member: confidence x magnitude x actionability."""
    confidence = _clamp01(event.get("confidence"))
    magnitude = _MAGNITUDE_WEIGHT.get(
        str(event.get("magnitude") or "medium").lower(), 1.0
    )
    actionability = _ACTIONABILITY_WEIGHT.get(
        str(event.get("actionability") or "medium").lower(), 1.0
    )
    return max(_MIN_WEIGHT, confidence * magnitude * actionability)


def _sectors_of(event: dict[str, Any]) -> list[str]:
    # "other" means no sector is moved; as a leg it produced "reduce other".
    return [s for s in normalize_sectors(event.get("sector_impact")) if s != "other"]


def _tickers_of(event: dict[str, Any]) -> list[str]:
    """Member tickers plus any ticker named on an affected entity."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in event.get("tickers") or []:
        symbol = str(raw).upper().strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    for entity in event.get("affected_entities") or []:
        if not isinstance(entity, dict):
            continue
        symbol = str(entity.get("ticker") or "").upper().strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def _analyzed_p(event: dict[str, Any]) -> float | None:
    """P(up) implied by the event's own analyzed signal_score (-5..5), or None."""
    try:
        score = max(-5.0, min(5.0, float(event.get("signal_score") or 0)))
    except (TypeError, ValueError):
        return None
    return 0.5 + 0.08 * score if score else None


def _member_p(event: dict[str, Any], prediction: dict[str, Any]) -> float:
    """Direction for one member.

    Without outcome data predict() falls back to lexicon sentiment over the prose,
    which ignores the analysis's own call and let related events advise opposite
    ways. Until outcomes exist, the analyzed signal_score leads.
    """
    predicted = float(prediction.get("p_positive_move", 0.5))
    analyzed = _analyzed_p(event)
    tier = str(prediction.get("data_tier") or "no-outcomes")
    if analyzed is None or tier == "empirical":
        return predicted
    return analyzed if tier == "no-outcomes" else (predicted + analyzed) / 2


def _tilt(p_positive: float) -> float:
    """Probability onto a signed -1..1 axis: 0.5 is no opinion."""
    return (p_positive - 0.5) * 2.0


def _rank(totals: dict[str, float], limit: int, scale: float) -> list[dict[str, Any]]:
    """Strongest legs first. Legs that net to zero carry no instruction and are
    dropped — the caller reports the cancellation, which is not the same thing
    as never having been exposed.

    Strength is tilt per unit of member weight, not share of the strongest leg:
    relative to the peak, a lone weak leg always drew a full bar.
    """
    live = {k: v for k, v in totals.items() if abs(v) > 1e-9}
    ranked = sorted(live.items(), key=lambda kv: abs(kv[1]), reverse=True)[:limit]
    peak = scale if scale > 0 else 1.0
    return [
        {
            "name": name,
            "direction": "up" if value > 0 else "down",
            "strength": round(min(1.0, abs(value) / peak), 3),
            "tilt": round(value, 3),
        }
        for name, value in ranked
    ]


def _advice(
    stance: str, sectors: list[dict], exposure: list[dict], touched: bool
) -> str:
    """One instruction, built from the two strongest legs on each side."""
    legs = sectors or exposure
    ups = [leg["name"] for leg in legs if leg["direction"] == "up"][:2]
    downs = [leg["name"] for leg in legs if leg["direction"] == "down"][:2]
    if not ups and not downs:
        return (
            "Mixed signal: exposure nets flat - monitor."
            if touched
            else "No tradable exposure identified - monitor only."
        )
    parts = []
    if downs:
        parts.append(f"reduce {', '.join(downs)}")
    if ups:
        parts.append(f"add {', '.join(ups)}")
    lead = {"mixed": "Mixed signal", "risk-on": "Risk-on", "risk-off": "Risk-off"}[
        stance
    ]
    return f"{lead}: {'; '.join(parts)}."


def _chain(members: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for member in members:
        for effect in member.get("second_order_effects") or []:
            text = str(effect).strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
    return out[:_MAX_CHAIN]


def score_scenario(
    cluster: dict[str, Any],
    outcomes: list[dict[str, Any]],
    predict_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    """One cluster to one scenario. None when the cluster carries no members."""
    members = [m for m in cluster.get("members") or [] if isinstance(m, dict)]
    if not members:
        return None

    weighted_p = 0.0
    total_weight = 0.0
    sector_tilt: dict[str, float] = {}
    ticker_tilt: dict[str, float] = {}
    tiers: list[str] = []
    sample_size = 0
    divergent = 0

    for member in members:
        weight = event_weight(member)
        sources = member.get("sources") or []
        subject = str(member.get("subject") or "")
        reasoning = str(member.get("reasoning") or "")
        prediction = predict_fn(
            text=f"{subject}. {reasoning}".strip(),
            verdict=str(member.get("verdict") or "OBSERVE"),
            confidence=_clamp01(member.get("confidence")),
            source=str(sources[0]).split("/")[-1] if sources else "local",
            event_type=str(member.get("event_type") or "other"),
            outcomes=outcomes,
        )
        p_positive = _member_p(member, prediction)
        tiers.append(str(prediction.get("data_tier") or "no-outcomes"))
        tables = prediction.get("reliability_tables") or {}
        sample_size = max(sample_size, int(tables.get("sample_size") or 0))
        weighted_p += p_positive * weight
        total_weight += weight
        if member.get("divergence_flag"):
            divergent += 1

        tilt = _tilt(p_positive) * weight
        for sector in _sectors_of(member):
            sector_tilt[sector] = sector_tilt.get(sector, 0.0) + tilt
        for ticker in _tickers_of(member):
            ticker_tilt[ticker] = ticker_tilt.get(ticker, 0.0) + tilt

    # The scenario is only as well-evidenced as its thinnest member, so report
    # the weakest tier rather than whichever one happened to be scored last.
    data_tier = (
        min(tiers, key=lambda t: _TIER_RANK.get(t, 0)) if tiers else "no-outcomes"
    )

    p_positive = weighted_p / total_weight if total_weight else 0.5
    tilt = _tilt(p_positive)
    if abs(tilt) < _MIXED_BAND:
        stance, direction = "mixed", "flat"
    elif tilt > 0:
        stance, direction = "risk-on", "up"
    else:
        stance, direction = "risk-off", "down"

    # Probability the scenario's own call lands, on the axis predict() puts a
    # single verdict on: never a number below a coin flip.
    probability = p_positive if p_positive >= 0.5 else 1.0 - p_positive

    member_ids = [m.get("id") for m in members if m.get("id") is not None]
    sectors = _rank(sector_tilt, _MAX_SECTORS, total_weight)
    exposure = _rank(ticker_tilt, _MAX_EXPOSURE, total_weight)

    return {
        "id": f"s{min(member_ids)}" if member_ids else "s0",
        "title": cluster.get("top_subject") or members[0].get("subject") or "Untitled",
        "size": len(members),
        "reports": int(cluster.get("reports") or len(members)),
        "probability": round(probability, 3),
        "direction": direction,
        "stance": stance,
        "tilt": round(tilt, 3),
        "data_tier": data_tier,
        "sample_size": sample_size,
        "divergent_members": divergent,
        "sectors": sectors,
        "exposure": exposure,
        "chain": _chain(members),
        "advice": _advice(stance, sectors, exposure, bool(sector_tilt or ticker_tilt)),
        "member_ids": member_ids,
        "sources": cluster.get("sources") or [],
        "first_seen": cluster.get("first_seen"),
    }


def build_scenarios(
    clusters: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    predict_fn: Callable[..., dict[str, Any]] | None = None,
    limit: int = 10,
    min_size: int = 2,
) -> list[dict[str, Any]]:
    """Score clusters into scenarios, strongest conviction first.

    `min_size` drops uncorroborated stories — one report is a headline, not a
    scenario — but falls back to them when nothing survives, so a quiet day
    still advises instead of rendering empty.

    Corroboration is counted in reports, not cluster members: the ingest
    pipeline merges same-story coverage into a single event, so a story carried
    by four outlets arrives as one member holding four articles.
    """
    if predict_fn is None:
        from finscrape.prediction import predict as _predict
        from finscrape.prediction import reliability_tables

        # predict() rebuilds these from `outcomes` on every call, and every
        # member of every cluster is one call. Build them once per request.
        tables = reliability_tables(outcomes)

        def predict_fn(**kwargs: Any) -> dict[str, Any]:
            return _predict(tables=tables, **kwargs)

    def _score(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored = [score_scenario(c, outcomes, predict_fn) for c in pool]
        return [s for s in scored if s]

    def _corroboration(cluster: dict[str, Any]) -> int:
        members = cluster.get("members") or []
        return max(int(cluster.get("reports") or 0), len(members))

    grouped = [c for c in clusters if _corroboration(c) >= min_size]
    scenarios = _score(grouped) or _score(clusters)
    scenarios.sort(
        key=lambda s: (abs(s["tilt"]) * s["probability"], s["size"]), reverse=True
    )
    return scenarios[:limit]
