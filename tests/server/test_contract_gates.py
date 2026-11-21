"""The API contract and the schema do not drift (plan M2.2).

Five gates, in one place because they are the same idea: the thing clients and the
database depend on is pinned, and a change to it has to be deliberate.

* the OpenAPI snapshot (`tests/snapshots/openapi.json`) refuses a removed path, a dropped
  response field, a parameter that became required or a bound that got tighter;
* every query bound the API documents is actually enforced with a 422;
* `/api/stats` — the shape `web/src/live.ts` polls — matches the server model field for
  field;
* the migration series, parsed from SQL, agrees with every column the code writes, and a
  fresh empty schema accepts the whole series exactly once;
* a seeded demo dataset fills the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi.testclient import TestClient

from scripts import openapi_snapshot
from server import db
from tests.server import schema_sql

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "tests" / "snapshots" / "openapi.json"
API_TS = ROOT / "web" / "src" / "api.ts"


def _app():
    from server.app import create_app

    return create_app()


# --------------------------------------------------------------------------- snapshot


def test_the_live_contract_matches_the_snapshot():
    problems = openapi_snapshot.compare(
        json.loads(SNAPSHOT.read_text(encoding="utf-8")), openapi_snapshot.build()
    )
    assert not problems, (
        "the API contract changed in a breaking way:\n  "
        + "\n  ".join(problems)
        + "\nIf this is intended, run `python -m scripts.openapi_snapshot --write`."
    )


def test_a_removed_path_is_a_breaking_change():
    old = {
        "paths": {
            "/api/events": {"get": {"parameters": {}, "auth": False, "responses": {}}}
        },
        "components": {},
    }
    assert openapi_snapshot.compare(old, {"paths": {}, "components": {}}) == [
        "removed path /api/events"
    ]


def test_a_dropped_response_field_is_a_breaking_change():
    old = {
        "paths": {},
        "components": {
            "DashboardStats": {
                "fields": {
                    "total_events": {"type": "integer"},
                    "last_update": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["total_events"],
            }
        },
    }
    new = {
        "paths": {},
        "components": {
            "DashboardStats": {
                "fields": {"total_events": {"type": "integer"}},
                "required": ["total_events"],
            }
        },
    }
    assert openapi_snapshot.compare(old, new) == [
        "removed field DashboardStats.last_update"
    ]


def test_a_tighter_bound_or_a_newly_required_parameter_is_a_breaking_change():
    old = {
        "paths": {
            "/api/events": {
                "get": {
                    "parameters": {
                        "limit": {
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "maximum": 500},
                        }
                    },
                    "auth": False,
                    "responses": {},
                }
            }
        },
        "components": {},
    }
    tighter = json.loads(json.dumps(old))
    tighter["paths"]["/api/events"]["get"]["parameters"]["limit"]["schema"][
        "maximum"
    ] = 200
    tighter["paths"]["/api/events"]["get"]["parameters"]["limit"]["required"] = True
    problems = openapi_snapshot.compare(old, tighter)
    assert "GET /api/events: parameter limit became required" in problems
    assert any("max narrowed 500 → 200" in p for p in problems)


def test_adding_a_path_or_a_param_is_not_a_breaking_change():
    old = {"paths": {}, "components": {}}
    new = {
        "paths": {
            "/api/new": {
                "get": {
                    "parameters": {
                        "x": {"in": "query", "required": False, "schema": {}}
                    },
                    "auth": False,
                    "responses": {},
                }
            }
        },
        "components": {},
    }
    assert openapi_snapshot.compare(old, new) == []


# --------------------------------------------------------------------- documented bounds


def _bounded_parameters() -> list[tuple[str, str, str, dict]]:
    """Every (path, method, param name, schema) the live app documents a bound for.

    Read from the live app, not the snapshot: the snapshot stores the numeric bounds a
    client can rely on, while the probe also needs the regex a symbol has to match.
    """
    out = []
    raw = _app().openapi()
    for path, ops in raw["paths"].items():
        for method, op in ops.items():
            for param in op.get("parameters", []):
                schema = param.get("schema") or {}
                bounded = {
                    "minimum",
                    "maximum",
                    "minLength",
                    "maxLength",
                    "enum",
                    "pattern",
                } & set(schema)
                if bounded and param.get("in") == "query":
                    out.append((path, method, param["name"], schema))
    return out


def _violation(schema: dict):
    """A value that must be refused, for whichever bound the parameter documents."""
    if "enum" in schema:
        return "definitely-not-in-the-enum"
    if "maximum" in schema:
        return schema["maximum"] + 1
    if "minimum" in schema:
        return schema["minimum"] - 1
    if "maxLength" in schema:
        return "A" * (schema["maxLength"] + 1)
    if schema.get("pattern"):
        # "!" is outside every character class this API admits (symbols, periods, intervals).
        return "!!!not-allowed!!!"
    if schema.get("type") == "integer":
        return "not-an-integer"
    return None


def test_the_snapshot_documents_the_bounds_it_claims_to():
    bounds = _bounded_parameters()
    assert len(bounds) >= 8, f"expected the documented query bounds, found {bounds}"


@pytest.mark.parametrize("path,method,name,schema", _bounded_parameters())
def test_every_documented_bound_is_enforced_with_422(path, method, name, schema):
    """A bound in the docs that the server ignores is a lie the frontend believes."""
    client = TestClient(_app())
    url = re.sub(r"\{[^}]+\}", "1", path)
    bad = _violation(schema)
    if bad is None:
        pytest.skip(f"{path} ?{name} has no boundary to violate")
    response = client.request(method.upper(), url, params={name: bad})
    assert response.status_code == 422, (
        f"{method.upper()} {url} ?{name}={bad} → {response.status_code}"
    )


def test_a_bad_date_is_named_in_the_error():
    client = TestClient(_app())
    response = client.get("/api/events", params={"date": "2026-02-30"})
    assert response.status_code == 422
    assert "date" in json.dumps(response.json())


# ------------------------------------------------------------------- /api/stats contract


def _ts_interface_fields() -> dict[str, str]:
    """The fields of `DashboardStats` in web/src/api.ts, as written."""
    text = API_TS.read_text(encoding="utf-8")
    match = re.search(r"export interface DashboardStats \{(.*?)\}", text, re.DOTALL)
    assert match, "DashboardStats is gone from web/src/api.ts — live.ts polls it"
    fields = {}
    for line in match.group(1).splitlines():
        line = line.split("//", 1)[0].strip().rstrip(";")
        if not line or ":" not in line:
            continue
        name, kind = line.split(":", 1)
        fields[name.strip()] = kind.strip()
    return fields


def test_the_stats_shape_live_ts_polls_is_the_shape_the_server_returns():
    ts_fields = _ts_interface_fields()
    schema = openapi_snapshot.build()["components"]["DashboardStats"]
    assert set(ts_fields) == set(schema["fields"]), (
        "web/src/api.ts DashboardStats and server/schemas.py DashboardStats disagree: "
        f"ts={sorted(ts_fields)} server={sorted(schema['fields'])}"
    )
    assert ts_fields["total_events"] == "number"
    # `last_update: string | null` on the client is a nullable timestamp on the server.
    assert "null" in ts_fields["last_update"]
    assert "null" in str(schema["fields"]["last_update"])


def test_the_stats_route_answers_the_documented_fields(monkeypatch):
    """The route's response model is what live.ts polls, so the keys are the contract."""
    from server.routes import events as events_routes

    async def fake_stats(pool):
        return {
            "total_events": 3,
            "by_verdict": {"INVEST": 3},
            "last_update": datetime(2026, 11, 24, 12, tzinfo=UTC),
        }

    monkeypatch.setattr(events_routes.queries, "get_stats", fake_stats)
    monkeypatch.setattr(events_routes.db, "pool", lambda: None)
    client = TestClient(_app())
    response = client.get("/api/stats")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"total_events", "by_verdict", "last_update"}
    assert isinstance(body["total_events"], int)
    assert isinstance(body["by_verdict"], dict)
    assert body["last_update"].startswith("2026-11-24T12:00:00")


# ---------------------------------------------------------------------- migration drift


def test_every_column_the_code_writes_exists_in_the_migrations():
    problems = schema_sql.drift()
    assert not problems, "\n".join(problems)


def test_the_parser_reads_the_real_migrations():
    """Guards the guard: a broken parser would report no drift forever."""
    tables = schema_sql.created_columns()
    assert "events" in tables and "content_hash" in tables["events"]
    assert (
        "accuracy_outcomes" in tables
        and "price_move_pct" in tables["accuracy_outcomes"]
    )
    assert len(schema_sql.insert_targets()) >= 8


def test_a_renamed_column_is_reported(tmp_path, monkeypatch):
    """The failure this exists for: a migration renames a column, a call site does not."""
    tables = schema_sql.created_columns()
    renamed = {
        name: [c for c in cols if c != "price_move_pct"]
        for name, cols in tables.items()
    }
    problems = schema_sql.drift(renamed)
    assert any("price_move_pct" in p for p in problems), problems


# ---------------------------------------------------------------- empty schema + idempotent


def _dsn() -> str:
    from tests.server import PG_DSN

    return PG_DSN


def _db_available() -> bool:
    from tests.server import pg_reachable

    try:
        return pg_reachable()
    except RuntimeError:
        return True  # WORLDFIN_REQUIRE_PG: the DB tests below fail loudly instead of skipping


needs_db = pytest.mark.skipif(not _db_available(), reason="no Postgres for the DB half")


@needs_db
def test_the_whole_series_applies_to_an_empty_schema():
    """Apply every migration to a scratch schema and compare it with the parsed SQL.

    The parser is how selfcheck knows the schema without a database; this proves the parser
    and a real Postgres agree, on an empty schema rather than one that drifted into shape.
    """
    import asyncpg

    async def body():
        conn = await asyncpg.connect(_dsn())
        try:
            await conn.execute("DROP SCHEMA IF EXISTS drift_check CASCADE")
            await conn.execute("CREATE SCHEMA drift_check")
            await conn.execute("SET search_path TO drift_check")
            files = sorted((ROOT / "server" / "migrations").glob("[0-9]*.sql"))
            for path in files:
                await conn.execute(path.read_text(encoding="utf-8"))
            rows = await conn.fetch(
                """
                SELECT table_name, column_name FROM information_schema.columns
                WHERE table_schema = 'drift_check' ORDER BY table_name, ordinal_position
                """
            )
            await conn.execute("DROP SCHEMA drift_check CASCADE")
        finally:
            await conn.close()
        actual: dict[str, list[str]] = {}
        for row in rows:
            actual.setdefault(row["table_name"], []).append(row["column_name"])
        return actual

    actual = asyncio.run(body())
    parsed = {
        t: c
        for t, c in schema_sql.created_columns().items()
        if t != "schema_migrations"
    }
    assert set(actual) == set(parsed), f"tables differ: {set(actual) ^ set(parsed)}"
    for table, columns in parsed.items():
        assert actual[table] == columns, f"{table}: {actual[table]} != {columns}"


@needs_db
def test_migrations_apply_once_and_are_idempotent():
    async def body():
        await db.disconnect()
        pool = await db.connect(_dsn())
        try:
            first = await db.run_migrations(pool)
            second = await db.run_migrations(pool)
            applied = await pool.fetchval("SELECT COUNT(*) FROM schema_migrations")
        finally:
            await db.disconnect()
        return first, second, applied

    _, second, applied = asyncio.run(body())
    assert second == [], "a second boot re-ran migrations"
    assert applied == len(list((ROOT / "server" / "migrations").glob("[0-9]*.sql")))


@needs_db
def test_the_seeded_dashboard_is_not_empty():
    """`make demo` on a fresh clone must land on real numbers, with no network."""
    from server.seed.loader import seed

    async def body():
        await db.disconnect()
        pool = await db.connect(_dsn())
        try:
            await db.run_migrations(pool)
            await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
            await seed(pool)
            stats = await pool.fetchrow(
                "SELECT COUNT(*) AS n, MAX(timestamp) AS last, "
                "COUNT(DISTINCT verdict) AS verdicts FROM events"
            )
        finally:
            await db.disconnect()
        return stats

    stats = asyncio.run(body())
    assert stats["n"] >= 12, "the demo dataset left the dashboard empty"
    assert stats["last"] is not None
    assert stats["verdicts"] >= 3
