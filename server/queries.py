"""Read queries + AI cache. All day-scoped reads use the SAME half-open [day, day+1)
bounds (server.ingest.day_bounds) so feed / dates / stats counts can't disagree.
"""

from __future__ import annotations

import re

import asyncpg

from server.ingest import day_bounds

# Whitelisted sort columns — never interpolate user input into SQL directly.
_SORT_COLS = {"timestamp", "signal_score", "confidence", "id", "created_at"}


# Rows the LLM judged off-topic after a heuristic-era ingest (scripts/reanalyse.py)
# stay stored but leave the feed and the counts.
_SHOWN = "coalesce(key_metrics->>'prompt_variant', '') <> 'rejected'"


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
    since_id: int | None = None,
    sort: str = "id",
    direction: str = "desc",
) -> list[dict]:
    conds: list[str] = [_SHOWN]
    params: list = []

    def p(v) -> str:
        params.append(v)
        return f"${len(params)}"

    if since_id is not None:
        # The 60 s poll asks for what landed since its last id, not the whole window
        # (plan M3.3). `id` is monotonic, so this is both cheap and exact.
        conds.append(f"id > {p(since_id)}")

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
    by_verdict = {
        r["verdict"]: r["c"]
        for r in await pool.fetch(
            f"SELECT verdict, COUNT(*) AS c FROM events WHERE {_SHOWN} GROUP BY verdict"
        )
    }
    total = sum(by_verdict.values())
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


async def get_ai_cache_for_event(pool: asyncpg.Pool, event_id: int) -> dict | None:
    """Newest real analysis for the event, whichever model wrote it.

    Rows cached before heuristic answers were flagged are recognised by their reasons.
    """
    row = await pool.fetchrow(
        "SELECT result FROM ai_analysis_cache WHERE event_id = $1 "
        "AND result->>'heuristic' IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements("
        "CASE WHEN jsonb_typeof(result->'ticker_impacts') = 'array' "
        "THEN result->'ticker_impacts' ELSE '[]'::jsonb END) t "
        "WHERE t->>'reason' = 'heuristic') "
        "ORDER BY created_at DESC LIMIT 1",
        event_id,
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


# --- Watchlists (plan m4.1.1) -------------------------------------------------

# One row per item, so a list is assembled without a second round trip and the
# ordering is stable (created_at, then id) rather than whatever the planner returns.
_WATCHLIST_SQL = """
SELECT w.id, w.name, w.created_at, wi.id AS item_id, wi.kind, wi.value
FROM watchlists w
LEFT JOIN watchlist_items wi ON wi.watchlist_id = w.id
WHERE w.owner_key = $1
ORDER BY w.created_at, w.id, wi.id
"""


def fold_watchlists(rows: list[asyncpg.Record]) -> list[dict]:
    """Group the join rows into watchlists with their items (pure, unit-tested)."""
    out: dict[int, dict] = {}
    for row in rows:
        watchlist = out.get(row["id"])
        if watchlist is None:
            watchlist = {
                "id": row["id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "items": [],
            }
            out[row["id"]] = watchlist
        if row["item_id"] is not None:
            watchlist["items"].append(
                {"id": row["item_id"], "kind": row["kind"], "value": row["value"]}
            )
    return list(out.values())


async def list_watchlists(pool: asyncpg.Pool, owner_key: str) -> list[dict]:
    return fold_watchlists(await pool.fetch(_WATCHLIST_SQL, owner_key))


async def create_watchlist(
    pool: asyncpg.Pool, owner_key: str, name: str, items: list[dict]
) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        watchlist_id = await conn.fetchval(
            "INSERT INTO watchlists (owner_key, name) VALUES ($1, $2) RETURNING id",
            owner_key,
            name.strip(),
        )
        for item in items:
            await conn.execute(
                "INSERT INTO watchlist_items (watchlist_id, kind, value) VALUES ($1, $2, $3)",
                watchlist_id,
                item["kind"],
                item["value"].strip(),
            )
        rows = await conn.fetch(_WATCHLIST_SQL, owner_key)
    return next(w for w in fold_watchlists(rows) if w["id"] == watchlist_id)


async def delete_watchlist(
    pool: asyncpg.Pool, owner_key: str, watchlist_id: int
) -> bool:
    status = await pool.execute(
        "DELETE FROM watchlists WHERE id = $1 AND owner_key = $2",
        watchlist_id,
        owner_key,
    )
    return status != "DELETE 0"


# A watchlist feed is one indexed pass over the items, not one query per item:
# tickers use the GIN index, sectors and the free-text kinds use ILIKE on the stored
# text. `region` has no column of its own, so it matches the story text (documented
# in docs/API.md); it is deliberately the loosest kind.
_FEED_SQL = """
SELECT DISTINCT e.*
FROM events e
JOIN watchlist_items wi ON wi.watchlist_id = $1
WHERE {shown}
  AND (
    (wi.kind = 'ticker' AND e.tickers ? wi.value)
    OR (wi.kind = 'sector' AND e.sector_impact ILIKE '%' || wi.value || '%')
    OR (
      wi.kind IN ('topic', 'region')
      AND (e.subject ILIKE '%' || wi.value || '%'
           OR e.reasoning ILIKE '%' || wi.value || '%')
    )
  )
ORDER BY e.id DESC
LIMIT $2
"""


async def get_watchlist_feed(
    pool: asyncpg.Pool, watchlist_id: int, owner_key: str, limit: int
) -> list[dict] | None:
    """None when the watchlist is not this owner's; [] when it simply has no matches."""
    owned = await pool.fetchval(
        "SELECT 1 FROM watchlists WHERE id = $1 AND owner_key = $2",
        watchlist_id,
        owner_key,
    )
    if owned is None:
        return None
    rows = await pool.fetch(_FEED_SQL.format(shown=_SHOWN), watchlist_id, limit)
    return [dict(row) for row in rows]


async def add_watchlist_item(
    pool: asyncpg.Pool, watchlist_id: int, owner_key: str, kind: str, value: str
) -> dict | None:
    """None when the list is not this owner's; the item row otherwise."""
    owned = await pool.fetchval(
        "SELECT 1 FROM watchlists WHERE id = $1 AND owner_key = $2",
        watchlist_id,
        owner_key,
    )
    if owned is None:
        return None
    row = await pool.fetchrow(
        "INSERT INTO watchlist_items (watchlist_id, kind, value) VALUES ($1, $2, $3) "
        "ON CONFLICT (watchlist_id, kind, value) DO NOTHING RETURNING id, kind, value",
        watchlist_id,
        kind,
        value.strip(),
    )
    if row is None:  # already followed: same answer, no error
        row = await pool.fetchrow(
            "SELECT id, kind, value FROM watchlist_items "
            "WHERE watchlist_id = $1 AND kind = $2 AND value = $3",
            watchlist_id,
            kind,
            value.strip(),
        )
    return dict(row) if row else None


async def remove_watchlist_item(
    pool: asyncpg.Pool, watchlist_id: int, owner_key: str, item_id: int
) -> bool:
    status = await pool.execute(
        "DELETE FROM watchlist_items wi USING watchlists w "
        "WHERE wi.id = $1 AND wi.watchlist_id = $2 AND w.id = wi.watchlist_id "
        "AND w.owner_key = $3",
        item_id,
        watchlist_id,
        owner_key,
    )
    return status != "DELETE 0"
