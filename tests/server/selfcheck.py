"""Docker-free Phase 0 self-check.

Validates the things that don't need a live Postgres: the migration SQL is
well-formed and complete, typed settings load with defaults, and the public
schemas validate a real finscrape FinEvent dict. Run standalone:

    python -m tests.server.selfcheck      # or: make selfcheck

SQL/structure checks use stdlib only and always run. Settings/schema checks need
the `server` dep group (pydantic); they're skipped with a notice if it's missing.
"""

from __future__ import annotations

import sys
from datetime import UTC
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "server" / "migrations"
MIGRATION = MIGRATIONS_DIR / "0001_init.sql"

REQUIRED_TABLES = [
    "events",
    "correlations",
    "scrape_runs",
    "source_health",
    "accuracy_outcomes",
    "ai_analysis_cache",
]


def check_migration_sql() -> None:
    sql = MIGRATION.read_text()
    low = sql.lower()

    for table in REQUIRED_TABLES:
        assert f"create table if not exists {table}" in low, f"missing table: {table}"

    # the dedup linchpin (Appendix B): content_hash must be UNIQUE
    assert "content_hash" in low and "unique" in low, (
        "events.content_hash UNIQUE missing"
    )
    # JSONB tickers need a GIN index for membership queries
    assert "using gin (tickers)" in low, "GIN index on events.tickers missing"
    # time discipline: TIMESTAMPTZ, not naive timestamps
    assert "timestamptz" in low, "expected TIMESTAMPTZ columns"
    # guard against the BIGGENERATED typo class
    assert "biggenerated" not in low, "typo: BIGGENERATED (want BIGINT GENERATED)"
    # cheap balance check on code only (strip -- comments so prose parens don't fool it)
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    assert code.count("(") == code.count(")"), "unbalanced parentheses in migration SQL"
    print(
        f"  ok  migration SQL: {len(REQUIRED_TABLES)} tables, UNIQUE+GIN+TIMESTAMPTZ present"
    )


def check_migration_series() -> None:
    """Every migration is applied once, in numeric order, so the series must be a clean
    sequence — a gap or a repeated prefix means a file silently never runs in order."""
    files = sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))
    assert files, "no migration files found"
    prefixes = []
    for path in files:
        head = path.name.split("_", 1)[0]
        assert head.isdigit() and len(head) == 4, f"bad migration name: {path.name}"
        prefixes.append(int(head))
    assert prefixes == list(range(1, len(prefixes) + 1)), (
        f"migration numbering is not contiguous from 0001: {prefixes}"
    )

    for path in files:
        # Comments carry prose parentheses; balance only the code.
        code = "\n".join(
            line.split("--", 1)[0] for line in path.read_text().splitlines()
        )
        assert code.count("(") == code.count(")"), f"unbalanced parens in {path.name}"

    combined = "\n".join(p.read_text() for p in files).lower()
    # One outcome per event, or /api/accuracy's denominator can be double-counted.
    assert "unique index if not exists idx_accuracy_event_unique" in combined, (
        "accuracy_outcomes (event_id) is not uniquely indexed"
    )
    print(f"  ok  migration series: {len(files)} files, contiguous, outcome key unique")


# Every env prefix Settings reads. A defaults check that leaves these in place
# reports the developer's shell, not the shipped defaults.
_SETTINGS_ENV_PREFIXES = (
    "WORLDFIN_",
    "FINSCRAPE_",
    "OPENAI_",
    "OPENROUTER_",
    "TELEGRAM_",
    "PORT",
)


def check_settings() -> bool:
    try:
        from server.settings import Settings
    except ImportError as exc:
        print(f"  skip settings/schema checks — server deps not installed ({exc})")
        return False
    import os
    from unittest.mock import patch

    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(_SETTINGS_ENV_PREFIXES)
    }
    with patch.dict(os.environ, clean, clear=True):
        s = Settings(_env_file=None)  # no .env, no ambient overrides
        assert s.database_url.startswith("postgresql://"), (
            "default DATABASE_URL malformed"
        )
        assert s.db_pool_max >= s.db_pool_min, "pool max < min"
        assert s.has_llm is False, "has_llm should be False with no LLM env set"
        assert s.redis_enabled is False, "redis_enabled should be False by default"
    print("  ok  settings load with sane defaults")
    return True


def check_schemas() -> None:
    from datetime import datetime

    from finscrape.models import FinEvent
    from server.schemas import EventIn, EventOut, IngestResponse

    fe = FinEvent(
        subject="Hormuz tanker incident disrupts oil shipping",
        event_type="geopolitical_event",
        tickers=["XOM", "CVX"],
        impact_direction="positive",
        signal_score=3,
        confidence=0.72,
        verdict="INVEST",
    )
    ev = EventIn.model_validate(fe.to_dict())  # ingest accepts a FinEvent dict verbatim
    assert ev.tickers == ["XOM", "CVX"]
    assert ev.event_type == "geopolitical_event"

    out = EventOut(id=1, created_at=datetime.now(UTC), **ev.model_dump())
    assert out.id == 1

    resp = IngestResponse(inserted=1, duplicates=0, inserted_ids=[1])
    assert resp.ok and resp.inserted == 1
    print("  ok  schemas validate a real FinEvent + ingest response")


def main() -> int:
    print("WorldFin Phase 0 self-check:")
    check_migration_sql()
    check_migration_series()
    if check_settings():
        check_schemas()
    print("self-check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
