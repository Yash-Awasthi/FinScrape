"""source_health + scrape_runs writes, and the /api/health aggregate.

STALE is derived at read time (now - fetched_at > threshold) rather than stored, so a
source that simply stopped reporting flips to STALE without anyone writing it.
"""

from __future__ import annotations

import asyncpg


async def record_source_health(
    pool: asyncpg.Pool, source: str, count: int, status: str, error: str | None = None
) -> None:
    await pool.execute(
        """
        INSERT INTO source_health (source, fetched_at, record_count, status, last_error)
        VALUES ($1, now(), $2, $3, $4)
        ON CONFLICT (source) DO UPDATE
          SET fetched_at = now(), record_count = $2, status = $3, last_error = $4
        """,
        source,
        count,
        status,
        error,
    )


async def record_feed_health(
    pool: asyncpg.Pool, feeds: dict[str, tuple[int, str | None]]
) -> None:
    """One `world/<key>` row per feed; rows for feeds no longer listed are dropped."""
    for key, (count, error) in feeds.items():
        await record_source_health(
            pool, f"world/{key}", count, "WARN" if error else "OK", error
        )
    await pool.execute(
        "DELETE FROM source_health WHERE source LIKE 'world/%' AND NOT (source = ANY($1::text[]))",
        [f"world/{k}" for k in feeds],
    )


async def start_scrape_run(pool: asyncpg.Pool, source: str) -> int:
    return await pool.fetchval(
        "INSERT INTO scrape_runs (status, details) VALUES ('running', $1) RETURNING id",
        {"source": source},
    )


async def finish_scrape_run(
    pool: asyncpg.Pool, run_id: int, status: str, events_ingested: int
) -> None:
    await pool.execute(
        "UPDATE scrape_runs SET finished_at = now(), status = $2, events_ingested = $3 WHERE id = $1",
        run_id,
        status,
        events_ingested,
    )


def derive_status(stored: str, age_s: float | None, stale_after_min: int) -> str:
    """An OK source whose last fetch is older than the window reads as STALE.
    Stored EMPTY/WARN are returned as-is. Pure — unit-tested without a DB."""
    if stored == "OK" and age_s is not None and age_s > stale_after_min * 60:
        return "STALE"
    return stored


async def aggregate_health(pool: asyncpg.Pool, stale_after_min: int = 60) -> list[dict]:
    """Per-source rows with STALE derived from age. EMPTY/WARN are stored as-is."""
    rows = await pool.fetch(
        """
        SELECT source, fetched_at, record_count, status,
               EXTRACT(EPOCH FROM (now() - fetched_at)) AS age_s
        FROM source_health ORDER BY source
        """
    )
    out: list[dict] = []
    for r in rows:
        status = derive_status(r["status"], r["age_s"], stale_after_min)
        out.append(
            {
                "source": r["source"],
                "status": status,
                "fetched_at": r["fetched_at"],
                "record_count": r["record_count"],
            }
        )
    return out
