"""Shared helpers for server/worker DB integration tests.

Integration tests skip cleanly when no Postgres is reachable at
WORLDFIN_TEST_DATABASE_URL, so the suite stays green without a database.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

# Deliberately not WORLDFIN_DATABASE_URL: these tests TRUNCATE, and sharing the
# app's variable is how a local corpus got wiped.
PG_DSN = os.getenv(
    "WORLDFIN_TEST_DATABASE_URL",
    "postgresql://worldfin:worldfin@localhost:5432/worldfin_test",
)
if not urlparse(PG_DSN).path.lstrip("/").endswith("_test"):
    raise RuntimeError(
        f"refusing to run destructive DB tests against {PG_DSN!r}: "
        "the database name must end in _test"
    )


def pg_reachable() -> bool:
    import asyncpg

    async def _check() -> bool:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(PG_DSN), timeout=2)
        except (TimeoutError, OSError, asyncpg.PostgresError):
            return False
        await conn.close()
        return True

    reachable = asyncio.run(_check())
    # CI sets this so a missing database fails the run instead of skipping it quietly.
    if not reachable and os.getenv("WORLDFIN_REQUIRE_PG"):
        raise RuntimeError(f"WORLDFIN_REQUIRE_PG is set but {PG_DSN!r} is unreachable")
    return reachable


async def fresh_pool(*truncate):
    """Connect, apply migrations, and TRUNCATE the named tables for a clean slate.

    Destructive; PG_DSN is guarded above to a database named *_test.
    """
    from server import db

    await db.disconnect()
    pool = await db.connect(PG_DSN)
    await db.run_migrations(pool)
    for table in truncate:
        await pool.execute(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
    return pool
