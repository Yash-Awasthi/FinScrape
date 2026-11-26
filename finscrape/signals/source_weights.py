"""Per-source hit rates and the small prior they earn.

A source's 90-day record says something about the source, not about the event in
front of you: it is worth a nudge, never a veto. `hit_rates` counts decided rows
inside the window; `prior` shrinks the rate toward a coin flip and returns a
multiplicative weight hard-bounded to [PRIOR_MIN, PRIOR_MAX].

Pure: no I/O. `now=None` reads the clock once, so callers can pin it in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# A source's record nudges its members, never overrides them. The rails keep the
# worst and the best recorded source within 1.35x of each other, so a small
# sample cannot dress noise up as a track record.
PRIOR_MIN = 0.85
PRIOR_MAX = 1.15
# Gentle slope: a 0.60 shrunk rate earns about +6%, which is a nudge, not a veto.
PRIOR_STEEP = 0.3
# Pseudo-count pulling a short record toward 0.5.
PRIOR_SHRINK = 5.0
MIN_N = 10
WINDOW_DAYS = 90


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        then = datetime.fromisoformat(str(value))
    except TypeError, ValueError:
        return None
    return then.replace(tzinfo=UTC) if then.tzinfo is None else then


def hit_rates(
    outcomes: list[dict[str, Any]],
    now: datetime | None = None,
    days: int = WINDOW_DAYS,
) -> dict[str, dict[str, Any]]:
    """Per-source {"n", "hits", "rate"} over the last `days` days.

    Only rows whose `checked_at` parses and falls inside the window count. A row
    with no (or unparseable) `checked_at` is excluded: the window cannot say
    whether it belongs, and assuming it is fresh would let an undated row vote.
    `outcome == "correct"` is a hit; every other value counts in `n` only, which
    is the same convention `reliability_tables` uses.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    cells: dict[str, dict[str, Any]] = {}
    for row in outcomes:
        then = _parse(row.get("checked_at"))
        if then is None or then < cutoff or then > now:
            continue
        source = str(row.get("source") or "unknown").split("/")[0]
        cell = cells.setdefault(source, {"n": 0, "hits": 0})
        cell["n"] += 1
        if row.get("outcome") == "correct":
            cell["hits"] += 1
    for cell in cells.values():
        cell["rate"] = round(cell["hits"] / cell["n"], 4)
    return cells


def prior(stats: dict[str, Any] | None, min_n: int = MIN_N) -> float:
    """Multiplicative weight for one source; exactly 1.0 below `min_n` outcomes.

    rate_shrunk = (hits + 5*0.5) / (n + 5), then a straight line through 1.0 at
    a coin-flip rate, clamped to [PRIOR_MIN, PRIOR_MAX]. Thin data never moves
    anything: below `min_n` the answer is 1.0, not a guess.
    """
    n = int((stats or {}).get("n") or 0)
    if n < min_n:
        return 1.0
    hits = float((stats or {}).get("hits") or 0)
    rate_shrunk = (hits + PRIOR_SHRINK * 0.5) / (n + PRIOR_SHRINK)
    raw = 1.0 + PRIOR_STEEP * (2.0 * rate_shrunk - 1.0)
    return round(min(PRIOR_MAX, max(PRIOR_MIN, raw)), 4)
