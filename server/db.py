"""asyncpg pool + versioned migration runner.

Migrations are plain .sql files in server/migrations/ named NNNN_*.sql. The runner
records each applied filename in schema_migrations and skips it next boot, so running
on every startup is idempotent (Phase 0 Verify). Each file runs in one transaction —
a failing migration rolls back and aborts startup loudly rather than half-applying.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger("worldfin.db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Round-trip JSONB as Python objects (so ingest passes lists/dicts directly and
    reads come back parsed) instead of raw strings."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def connect(dsn: str, *, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Create the global pool. Call once at startup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn, min_size=min_size, max_size=max_size, init=_init_conn
        )
        log.info("db pool created (min=%d max=%d)", min_size, max_size)
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("db pool closed")


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db pool not initialized — call connect() first")
    return _pool


def _migration_files() -> list[Path]:
    """All migration files, sorted by their numeric prefix."""
    return sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))


_MIGRATION_LOCK = 0x574F524C  # any constant shared by every runner


async def run_migrations(p: asyncpg.Pool) -> list[str]:
    """Apply any unapplied migrations in order. Returns the filenames applied this call."""
    async with p.acquire() as conn:
        # The API and `server.seed` may start together; one runner at a time.
        await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK)
        try:
            return await _migrate(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK)


async def _migrate(conn: asyncpg.pool.PoolConnectionProxy) -> list[str]:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    done = {
        r["filename"]
        for r in await conn.fetch("SELECT filename FROM schema_migrations")
    }

    applied: list[str] = []
    for path in _migration_files():
        if path.name in done:
            continue
        sql = path.read_text()
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
            )
        applied.append(path.name)
        log.info("applied migration %s", path.name)

    if not applied:
        log.info("no new migrations (%d already applied)", len(done))
    return applied
