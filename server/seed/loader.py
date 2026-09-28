"""Curated demo loader. Resolves the dataset's relative day offsets to absolute UTC
timestamps at load time (so every launch shows fresh signal), ingests via the same
deterministic-dedup path as the API (idempotent on same-day re-runs), then seeds
accuracy_outcomes for the directional events and the correlation signals.

Pure resolution (`resolve_events`) is unit-testable without a DB; only `seed` needs a
live pool. Re-running is safe: events dedup by content_hash, accuracy rows are written
only for *newly inserted* events, and seed correlations are replaced (DELETE seed:* first).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg

from server.ingest import ingest_events

DATA_FILE = Path(__file__).with_name("demo_events.json")

# Keys that live in the dataset but are not event columns.
_SEED_ONLY = ("days_ago", "hour", "accuracy", "_skip", "_comment")


def resolve_events(
    raw_events: list[dict], now: datetime
) -> tuple[list[dict], dict[str, dict]]:
    """Turn dataset rows (relative day offset) into ingest-ready event dicts with an
    absolute UTC `timestamp`. Returns (events, accuracy_by_subject)."""
    events: list[dict] = []
    accuracy_by_subject: dict[str, dict] = {}
    for row in raw_events:
        if row.get("_skip"):
            continue
        ev = {k: v for k, v in row.items() if k not in _SEED_ONLY}
        day = (now - timedelta(days=int(row.get("days_ago", 0)))).date()
        ts = datetime(
            day.year, day.month, day.day, int(row.get("hour", 12)), tzinfo=UTC
        )
        ev["timestamp"] = ts.isoformat()
        events.append(ev)
        if row.get("accuracy"):
            accuracy_by_subject[ev["subject"]] = row["accuracy"]
    return events, accuracy_by_subject


def load_dataset() -> dict:
    return json.loads(DATA_FILE.read_text())


async def seed(pool: asyncpg.Pool, now: datetime | None = None) -> dict:
    """Load the curated dataset into a live pool. Returns a counts summary."""
    now = now or datetime.now(UTC)
    data = load_dataset()
    events, accuracy_by_subject = resolve_events(data.get("events", []), now)

    result = await ingest_events(pool, events)

    # accuracy_outcomes — only for events inserted THIS run (keeps re-seed idempotent).
    accuracy_written = 0
    for inserted in result["inserted_rows"]:
        acc = accuracy_by_subject.get(inserted["subject"])
        if not acc:
            continue
        ticker = (inserted.get("tickers") or ["?"])[0]
        await pool.execute(
            "INSERT INTO accuracy_outcomes (event_id, ticker, verdict, price_move_pct, correct) "
            "VALUES ($1, $2, $3, $4, $5)",
            inserted["id"],
            ticker,
            inserted["verdict"],
            acc.get("price_move_pct"),
            acc.get("correct"),
        )
        accuracy_written += 1

    # correlations — replace the seed set so re-runs don't pile up.
    await pool.execute("DELETE FROM correlations WHERE dedupe_key LIKE 'seed:%'")
    correlations = data.get("correlations", [])
    for i, c in enumerate(correlations):
        await pool.execute(
            "INSERT INTO correlations (dedupe_key, signal_type, confidence, payload) "
            "VALUES ($1, $2, $3, $4)",
            f"seed:{c['signal_type']}:{i}",
            c["signal_type"],
            float(c["confidence"]),
            c.get("payload", {}),
        )

    return {
        "events_inserted": result["inserted"],
        "events_duplicate": result["duplicates"],
        "accuracy_outcomes": accuracy_written,
        "correlations": len(correlations),
    }
