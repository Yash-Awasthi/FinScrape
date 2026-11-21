"""Market confirmation: one-day price/volume reaction as evidence, not a signal.

The NLP/LLM call decides the event and its direction. This layer asks whether the
related listed expression moved the same way with abnormal turnover. It can lift
magnitude/confidence and, when the move is extreme, add at most two points to the
score. It never changes the sign and never turns a 0 into a call, so a stock spike
cannot manufacture an event that the text did not contain.
"""

from __future__ import annotations

from dataclasses import dataclass

# Extreme: a genuine repricing, not noise. Strong: a clear move with participation.
_EXTREME_MOVE = 15.0
_EXTREME_VOLUME = 1.5
_STRONG_MOVE = 7.0
_STRONG_VOLUME = 1.2
_MODERATE_MOVE = 3.0
_MODERATE_VOLUME = 1.5
_OPPOSING_MOVE = 10.0


@dataclass(frozen=True)
class MarketConfirmation:
    """Adjustments suggested by the tape. `delta` is always >= 0."""

    delta: int = 0
    confidence: float = 0.0
    magnitude: str = ""
    actionability: str = ""
    evidence: str = ""


def apply_market_confirmation(
    score: int,
    direction: str,
    reaction: dict[str, dict],
) -> MarketConfirmation:
    """Compare the event direction with the one-day move of its tickers.

    `direction` is the analysis `impact_direction`; when it is neutral/mixed the
    score sign is used. A missing reaction is no evidence, not confirmation.
    """
    if score == 0 or not reaction:
        return MarketConfirmation()

    side = 1 if score > 0 else -1
    if direction == "positive":
        side = 1
    elif direction == "negative":
        side = -1

    candidates: list[tuple[float, dict]] = []
    opposing: list[dict] = []
    for row in reaction.values():
        try:
            change = float(row.get("change_percent", 0.0))
            volume_ratio = float(row.get("volume_ratio", 1.0) or 1.0)
        except TypeError, ValueError:
            continue
        if change * side > 0:
            # Prefer a large move with participation, not a thin spike.
            candidates.append((abs(change) * min(max(volume_ratio, 0.5), 5.0), row))
        elif abs(change) >= _OPPOSING_MOVE and volume_ratio >= _EXTREME_VOLUME:
            opposing.append(row)

    if not candidates:
        if opposing:
            row = max(
                opposing, key=lambda item: abs(float(item.get("change_percent", 0)))
            )
            return MarketConfirmation(
                confidence=-0.05,
                evidence=(
                    f"{row.get('ticker', 'ticker')} moved {float(row.get('change_percent', 0)):+.1f}% "
                    f"against the event direction"
                ),
            )
        return MarketConfirmation()

    row = max(candidates, key=lambda item: item[0])[1]
    move = abs(float(row.get("change_percent", 0)))
    volume_ratio = float(row.get("volume_ratio", 1.0) or 1.0)
    ticker = str(row.get("ticker") or "ticker")
    evidence = f"{ticker} moved {move:.1f}% on {volume_ratio:.1f}x 20-day volume"

    if move >= _EXTREME_MOVE and volume_ratio >= _EXTREME_VOLUME:
        return MarketConfirmation(
            delta=2,
            confidence=0.05,
            magnitude="high",
            actionability="high",
            evidence=evidence,
        )
    if move >= _STRONG_MOVE and volume_ratio >= _STRONG_VOLUME:
        return MarketConfirmation(
            delta=1,
            confidence=0.04,
            magnitude="high" if move >= 10 else "medium",
            actionability="medium",
            evidence=evidence,
        )
    if move >= _MODERATE_MOVE and volume_ratio >= _MODERATE_VOLUME:
        return MarketConfirmation(confidence=0.02, evidence=evidence)
    return MarketConfirmation()
