"""Event ingestion + deterministic dedup — the root-cause fix for the live ~4× dup
and count-mismatch bugs.

The dedup linchpin is a deterministic `content_hash` = normalized subject + UTC day,
enforced by a UNIQUE constraint with ON CONFLICT DO UPDATE. That kills duplication
atomically at the DB layer (no read-then-write race, no fragile `instr(articles, url)`
substring match) and lets one story that reaches us three times — world RSS, GDELT and
a blocked-feed fallback — land as ONE row whose `sources` and `articles` are the union
of all three. The URL is deliberately out of the key: the same story carries a
different URL per source, so keying on it is what produced one row per source.

The pure helpers below carry all the load-bearing logic, so they're unit-tested
without a database; only `ingest_events` needs a live pool.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
from dateutil import parser as dtparser

# Tracking/junk query params dropped during URL canonicalization.
_JUNK_PARAMS = ("fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src")

# Columns written on insert, in order. Mirrors finscrape FinEvent + geo + content_hash.
_INSERT_COLS = [
    "content_hash",
    "subject",
    "event_type",
    "impact_direction",
    "signal_score",
    "confidence",
    "verdict",
    "heuristic_impact",
    "divergence_flag",
    "reasoning",
    "magnitude",
    "novelty",
    "actionability",
    "sector_impact",
    "tickers",
    "sources",
    "articles",
    "affected_entities",
    "second_order_effects",
    "key_metrics",
    "analysis_source",
    "model_name",
    "lat",
    "lon",
    "timestamp",
]


def normalize_subject(subject: str) -> str:
    """Lowercase + collapse whitespace. Stable across trivial formatting differences."""
    return " ".join((subject or "").split()).lower()


def canonical_url(url: str) -> str:
    """Canonicalize so trivially-different URLs hash equal: lowercase scheme/host,
    strip trailing slash + fragment, drop tracking params, sort the rest."""
    if not url or not url.strip():
        return ""
    s = urlsplit(url.strip())
    scheme = (s.scheme or "http").lower()
    netloc = s.netloc.lower()
    path = s.path.rstrip("/") or "/"
    kept = [
        (k, v)
        for k, v in parse_qsl(s.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _JUNK_PARAMS
    ]
    query = urlencode(sorted(kept))
    return urlunsplit((scheme, netloc, path, query, ""))


def parse_timestamp(ts: str | None) -> datetime:
    """Parse an ISO timestamp to an aware UTC datetime. Naive input is assumed UTC.
    Missing/garbage input falls back to now(UTC). This is THE timezone-normalization
    point — everything downstream is UTC, so the one day-bounds convention holds."""
    if ts:
        try:
            dt = dtparser.isoparse(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError, OverflowError, TypeError:
            pass
    return datetime.now(UTC)


def content_hash(subject: str, ts: datetime) -> str:
    """Deterministic dedup key: norm(subject) + UTC day.

    The URL is intentionally not part of the key (plan M1.5): RSS, GDELT and a
    blocked-feed fallback each hand us the same story with a different link, so a
    URL-keyed hash inserted it three times. Same story, same UTC day → same hash →
    one row, and `ingest_events` merges the sources/articles onto it.
    """
    day = ts.astimezone(UTC).date().isoformat()
    key = f"{normalize_subject(subject)}|{day}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def day_bounds(date_str: str) -> tuple[datetime, datetime]:
    """Half-open [day, day+1) UTC bounds for a 'YYYY-MM-DD' string. The ONE convention
    reused by feed / dates / stats so their counts can never disagree (Appendix B)."""
    d = date.fromisoformat(date_str)
    start = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _row_values(ev: dict) -> list:
    """Map a (pydantic-validated) event dict → ordered INSERT values. JSONB columns
    are passed as Python objects; the pool's jsonb codec encodes them."""
    ts = parse_timestamp(ev.get("timestamp"))
    return [
        content_hash(ev["subject"], ts),
        ev["subject"],
        ev.get("event_type", "other"),
        ev.get("impact_direction", "neutral"),
        int(ev.get("signal_score", 0)),
        float(ev.get("confidence", 0.0)),
        ev["verdict"],
        float(ev.get("heuristic_impact", 0.0)),
        bool(ev.get("divergence_flag", False)),
        ev.get("reasoning", ""),
        ev.get("magnitude", "medium"),
        ev.get("novelty", "standard"),
        ev.get("actionability", "medium"),
        ev.get("sector_impact", ""),
        ev.get("tickers", []),
        ev.get("sources", []),
        ev.get("articles", []),
        ev.get("affected_entities", []),
        ev.get("second_order_effects", []),
        ev.get("key_metrics", {}),
        ev.get("analysis_source", "unknown"),
        ev.get("model_name", ""),
        ev.get("lat"),
        ev.get("lon"),
        ts,
    ]


def _insert_sql() -> str:
    placeholders = ", ".join(f"${i}" for i in range(1, len(_INSERT_COLS) + 1))
    cols = ", ".join(_INSERT_COLS)
    # A repeat story merges instead of vanishing: the row keeps its first verdict and
    # analysis, and the sources/articles become the union of every report (plan M1.5).
    # `xmax = 0` is true only for a real insert, so the caller can still count both.
    return (
        f"INSERT INTO events ({cols}) VALUES ({placeholders}) "
        "ON CONFLICT (content_hash) DO UPDATE SET "
        "sources = (SELECT COALESCE(jsonb_agg(DISTINCT s ORDER BY s), '[]'::jsonb) "
        "           FROM jsonb_array_elements_text(events.sources || EXCLUDED.sources) AS s), "
        "articles = (SELECT COALESCE(jsonb_agg(DISTINCT a ORDER BY a), '[]'::jsonb) "
        "            FROM jsonb_array_elements_text(events.articles || EXCLUDED.articles) AS a) "
        "RETURNING id, (xmax = 0) AS inserted"
    )


async def ingest_events(pool: asyncpg.Pool, events: list[dict]) -> dict:
    """Insert events, deduping atomically by content_hash and merging repeat sources.

    Returns {inserted, merged, duplicates, inserted_ids, inserted_rows}. A repeat
    (ON CONFLICT) keeps the original row and its id, widens sources/articles, and is
    counted in both `merged` (rows that gained something) and `duplicates` (the
    metric the worker already records), so old dashboards keep working.
    """
    sql = _insert_sql()
    inserted_ids: list[int] = []
    inserted_rows: list[dict] = []
    duplicates = 0
    merged = 0

    async with pool.acquire() as conn:
        for ev in events:
            row = await conn.fetchrow(sql, *_row_values(ev))
            if row is None:  # unreachable while the conflict clause returns a row
                duplicates += 1
                continue
            if not row["inserted"]:
                duplicates += 1
                merged += 1
                continue
            inserted_ids.append(row["id"])
            inserted_rows.append({**ev, "id": row["id"]})

    return {
        "inserted": len(inserted_ids),
        "merged": merged,
        "duplicates": duplicates,
        "inserted_ids": inserted_ids,
        "inserted_rows": inserted_rows,
    }
