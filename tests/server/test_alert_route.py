"""Alert rules over the API (plan t13): quiet hours round-trip, validation, firing.

The pool is faked like tests/server/test_scenario_route.py: the route and the firing
loop are what these pin, not Postgres.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import alert_rules
from server.routes import alerts as alert_routes
from server.settings import DEFAULT_API_KEY

AUTH = {"X-API-Key": DEFAULT_API_KEY}


class FakePool:
    """alert_rules rows in memory, plus the history the firing loop writes."""

    def __init__(self, rows: list[dict] | None = None):
        self.rows = list(rows or [])
        self.statements: list[tuple[str, tuple]] = []
        self.history: list[tuple] = []

    async def fetch(self, sql, *args):
        self.statements.append((sql, args))
        if "FROM alert_history" in sql:
            return []
        return self.rows

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        if sql.startswith("INSERT INTO alert_rules"):
            rule_id, name, conditions, actions, quiet_hours = args
            self.rows.append(
                {
                    "id": rule_id,
                    "name": name,
                    "conditions": conditions,
                    "actions": actions,
                    "enabled": True,
                    "created_at": datetime.now(UTC),
                    "quiet_hours": quiet_hours,
                }
            )
            return "INSERT 0 1"
        return "OK"

    async def executemany(self, sql, args):
        self.statements.append((sql, list(args)))
        self.history.extend(args)


def _client(monkeypatch, pool: FakePool) -> TestClient:
    app = FastAPI()
    app.include_router(alert_routes.router)
    monkeypatch.setattr(alert_routes.db, "pool", lambda: pool)
    return TestClient(app)


def _body(**overrides) -> dict:
    body = {
        "name": "Energy exits",
        "conditions": [{"field": "verdict", "operator": "eq", "value": "PULL_OUT"}],
        "actions": [{"action_type": "telegram", "config": {}}],
    }
    body.update(overrides)
    return body


def _row(rule_id: str, quiet_hours: dict | None = None) -> dict:
    row = {
        "id": rule_id,
        "name": rule_id,
        "conditions": [{"field": "verdict", "operator": "eq", "value": "INVEST"}],
        "actions": [{"action_type": "log", "config": {}}],
        "enabled": True,
        "created_at": datetime(2026, 5, 3, 9, 0, tzinfo=UTC),
    }
    if quiet_hours is not None:
        row["quiet_hours"] = quiet_hours
    return row


def test_quiet_hours_round_trip_through_post_and_get(monkeypatch) -> None:
    pool = FakePool()
    client = _client(monkeypatch, pool)
    quiet = {"start": "22:00", "end": "06:00"}

    created = client.post(
        "/api/alerts/rules", json=_body(quiet_hours=quiet), headers=AUTH
    )
    assert created.status_code == 200
    assert created.json()["rule"]["quiet_hours"] == quiet
    insert = [
        sql for sql, _ in pool.statements if sql.startswith("INSERT INTO alert_rules")
    ]
    assert insert and "quiet_hours" in insert[0]

    listed = client.get("/api/alerts/rules").json()["rules"]
    assert listed[0]["quiet_hours"] == quiet


def test_a_rule_without_the_column_reads_as_no_quiet_hours(monkeypatch) -> None:
    # Older rows and a NULL column both arrive without a usable window.
    pool = FakePool([_row("old")])
    body = _client(monkeypatch, pool).get("/api/alerts/rules").json()
    assert body["rules"][0]["quiet_hours"] == {}


@pytest.mark.parametrize(
    "quiet",
    [
        {"start": "25:00", "end": "06:00"},
        {"start": "22:60", "end": "06:00"},
        {"start": "7:00", "end": "08:00"},
        {"start": "22:00"},
        "22:00-06:00",
        {"start": "22:00", "end": "06:00", "tz": "UTC"},
    ],
)
def test_bad_quiet_hours_is_a_400_and_writes_nothing(monkeypatch, quiet) -> None:
    pool = FakePool()
    response = _client(monkeypatch, pool).post(
        "/api/alerts/rules", json=_body(quiet_hours=quiet), headers=AUTH
    )
    assert response.status_code == 400
    assert not pool.rows


def test_an_empty_quiet_hours_object_is_accepted_as_no_window(monkeypatch) -> None:
    pool = FakePool()
    created = _client(monkeypatch, pool).post(
        "/api/alerts/rules", json=_body(quiet_hours={}), headers=AUTH
    )
    assert created.status_code == 200
    assert created.json()["rule"]["quiet_hours"] == {}


def test_fire_alerts_skips_a_rule_inside_its_quiet_window() -> None:
    # start == end is the whole day, so the skip does not depend on the wall clock.
    all_day = {"start": "00:00", "end": "00:00"}
    pool = FakePool([_row("loud"), _row("quiet", all_day)])
    event = {
        "id": 7,
        "verdict": "INVEST",
        "subject": "Apple beats",
        "tickers": ["AAPL"],
        "signal_score": 3,
    }

    fired = asyncio.run(alert_rules.fire_alerts(pool, [event]))

    assert fired == 1
    assert [row[0] for row in pool.history] == ["loud"]
    history_sql = [
        sql for sql, _ in pool.statements if "INSERT INTO alert_history" in sql
    ]
    assert len(history_sql) == 1


def test_fire_alerts_counts_only_actions_it_runs() -> None:
    pool = FakePool([_row("quiet", {"start": "00:00", "end": "00:00"})])
    event = {"id": 8, "verdict": "INVEST", "tickers": ["AAPL"], "signal_score": 3}

    assert asyncio.run(alert_rules.fire_alerts(pool, [event])) == 0
    assert pool.history == []
