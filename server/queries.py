"""Read queries + AI cache. All day-scoped reads use the SAME half-open [day, day+1)
bounds (server.ingest.day_bounds) so feed / dates / stats counts can't disagree.
"""

from __future__ import annotations

import re

import asyncpg

from server.ingest import day_bounds

# Whitelisted sort columns — never interpolate user input into SQL directly.
_SORT_COLS = {"timestamp", "signal_score", "confidence", "id", "created_at"}


async def get_events(
    pool: asyncpg.Pool,
    *,
    limit: int = 100,
    offset: int = 0,
    date: str | None = None,
    verdict: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    sort: str = "id",
    direction: str = "desc",
) -> list[dict]:
    # Rows the LLM judged off-topic after a heuristic-era ingest (scripts/reanalyse.py).
    conds: list[str] = ["coalesce(key_metrics->>'prompt_variant', '') <> 'rejected'"]
    params: list = []

    def p(v) -> str:
        params.append(v)
        return f"${len(params)}"

    if date:
        start, end = day_bounds(date)
        conds.append(f"timestamp >= {p(start)} AND timestamp < {p(end)}")
    if verdict:
        conds.append(f"verdict = {p(verdict)}")
    if ticker:
        conds.append(f"tickers ? {p(ticker)}")  # jsonb array membership (GIN-indexed)
    if source:
        conds.append(f"sources ? {p(source)}")
    if event_type:
        conds.append(f"event_type = {p(event_type)}")

    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    sort_col = sort if sort in _SORT_COLS else "id"
    sort_dir = "ASC" if direction.lower() == "asc" else "DESC"
    sql = (
        f"SELECT * FROM events {where} "
        f"ORDER BY {sort_col} {sort_dir} LIMIT {p(limit)} OFFSET {p(offset)}"
    )
    rows = await pool.fetch(sql, *params)
    return [dict(r) for r in rows]


async def count_events_for_date(pool: asyncpg.Pool, date: str) -> int:
    start, end = day_bounds(date)
    return await pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE timestamp >= $1 AND timestamp < $2",
        start,
        end,
    )


async def get_stats(pool: asyncpg.Pool) -> dict:
    total = await pool.fetchval("SELECT COUNT(*) FROM events")
    by_verdict = {
        r["verdict"]: r["c"]
        for r in await pool.fetch(
            "SELECT verdict, COUNT(*) AS c FROM events GROUP BY verdict"
        )
    }
    last_update = await pool.fetchval("SELECT MAX(created_at) FROM events")
    return {"total_events": total, "by_verdict": by_verdict, "last_update": last_update}


async def get_dates(pool: asyncpg.Pool, limit: int = 90) -> list[dict]:
    rows = await pool.fetch(
        "SELECT (timestamp AT TIME ZONE 'UTC')::date AS day, COUNT(*) AS c "
        "FROM events GROUP BY day ORDER BY day DESC LIMIT $1",
        limit,
    )
    return [{"day": r["day"].isoformat(), "count": r["c"]} for r in rows]


async def get_event_by_id(pool: asyncpg.Pool, event_id: int) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
    return dict(row) if row else None


async def get_ai_cache(pool: asyncpg.Pool, cache_key: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT result FROM ai_analysis_cache WHERE cache_key = $1", cache_key
    )
    return row["result"] if row else None


async def save_ai_cache(
    pool: asyncpg.Pool, cache_key: str, event_id: int, result: dict
) -> list[str]:
    """Cache the analysis and merge AI-found tickers (≤6 chars) into the event.
    Returns the merged ticker list (so the caller can broadcast the update)."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO ai_analysis_cache (cache_key, event_id, result) "
            "VALUES ($1, $2, $3) ON CONFLICT (cache_key) DO UPDATE SET result = EXCLUDED.result",
            cache_key,
            event_id,
            result,
        )
        existing = await conn.fetchval(
            "SELECT tickers FROM events WHERE id = $1", event_id
        )
        existing = existing or []
        ai_tickers = [
            ti["ticker"]
            for ti in result.get("ticker_impacts", [])
            if isinstance(ti, dict) and ti.get("ticker") and len(ti["ticker"]) <= 6
        ]
        merged = list(dict.fromkeys([*existing, *ai_tickers]))
        if len(merged) > len(existing):
            await conn.execute(
                "UPDATE events SET tickers = $1 WHERE id = $2", merged, event_id
            )
        return merged


# --- AI-derived predictions (feeds correlate.detect_prediction_leads_news) ---

_PCT_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def impact_shift(impact: dict) -> float | None:
    """Signed % move one AI ticker-impact predicts, or None when it names none.

    Magnitude is the mean of the numbers in `estimated_pct` ("+3-5%" -> 4). The sign
    comes from `direction`, never from the string: the '-' in a range is a separator,
    not a minus. A neutral or unlabelled direction is not a directional call.
    """
    if not isinstance(impact, dict):
        return None
    numbers = [
        float(n) for n in _PCT_NUMBER.findall(str(impact.get("estimated_pct", "")))
    ]
    if not numbers:
        return None
    magnitude = sum(numbers) / len(numbers)
    direction = str(impact.get("direction", "")).strip().lower()
    if direction == "up":
        return magnitude
    if direction == "down":
        return -magnitude
    return None


async def get_recent_predictions(
    pool: asyncpg.Pool, hours: float = 24
) -> dict[str, float]:
    """ticker -> strongest predicted % move across cached AI analyses of recent events.

    Best-effort: the cache only holds events someone (or the ingest path) analyzed,
    so an empty result just means no predictions this window.
    """
    rows = await pool.fetch(
        "SELECT c.result FROM ai_analysis_cache c JOIN events e ON e.id = c.event_id "
        "WHERE e.timestamp >= now() - ($1 || ' hours')::interval",
        str(hours),
    )
    strongest: dict[str, float] = {}
    for row in rows:
        result = row["result"] or {}
        for impact in result.get("ticker_impacts") or []:
            shift = impact_shift(impact)
            if shift is None:
                continue
            ticker = str(impact.get("ticker", "")).upper().strip()
            if ticker and abs(shift) > abs(strongest.get(ticker, 0.0)):
                strongest[ticker] = shift
    return strongest
