"""Fail the ingest run when production stops getting events or nears the 500 MB cap.

GitHub emails the owner on a failed run, which is the alert.
"""

import asyncio
import os
import sys

import asyncpg

MAX_MB = 400


def max_age_hours(every_hours: str | None) -> int:
    """Two ingest intervals plus an hour: one run that finds no news is not an outage."""
    every = int(every_hours) if (every_hours or "").isdigit() and int(every_hours) > 0 else 24
    return 2 * every + 1


async def main() -> int:
    conn = await asyncpg.connect(os.environ["WORLDFIN_DATABASE_URL"])
    try:
        age = await conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM now() - max(created_at)) / 3600 FROM events"
        )
        size = await conn.fetchval("SELECT pg_database_size(current_database())")
    finally:
        await conn.close()
    mb = size / 1e6
    max_age = max_age_hours(os.environ.get("INGEST_EVERY_HOURS"))
    print(f"newest event {age or 0:.1f}h old, database {mb:.0f} MB")
    problems = []
    if age is None or age > max_age:
        problems.append(f"no new event for {max_age}h")
    if mb > MAX_MB:
        problems.append(f"database over {MAX_MB} MB of the 500 MB free cap")
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
