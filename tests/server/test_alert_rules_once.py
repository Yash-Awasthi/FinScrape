"""A rule fires an action once per event, and re-scoring the event fires nothing.

Pure: a fake pool answers the rule and history queries, so no database is needed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

pytest.importorskip("asyncpg")

from server.alert_rules import fire_alerts

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
EVENT = {"id": 11, "verdict": "INVEST", "tickers": ["AAPL"], "subject": "Apple"}


def _rule(rule_id: str, *action_types: str) -> dict:
    return {
        "id": rule_id,
        "name": rule_id,
        "conditions": [{"field": "verdict", "operator": "eq", "value": "INVEST"}],
        "actions": [{"action_type": t} for t in action_types],
        "enabled": True,
        "created_at": NOW,
    }


class FakePool:
    def __init__(self, rules: list[dict]) -> None:
        self.rules = rules
        self.history: list[dict] = []

    async def fetch(self, sql, *args):
        if "FROM alert_rules" in sql:
            return list(self.rules)
        assert "FROM alert_history" in sql
        wanted = set(args[0])
        return [dict(r) for r in self.history if r["event_id"] in wanted]

    async def executemany(self, sql, rows):
        assert "INSERT INTO alert_history" in sql
        for rule_id, event_id, action_type, status in rows:
            self.history.append(
                {
                    "rule_id": rule_id,
                    "event_id": event_id,
                    "action_type": action_type,
                    "status": status,
                }
            )


def test_one_event_fires_each_matching_rule_once() -> None:
    pool = FakePool([_rule("r1", "log"), _rule("r2", "log")])

    assert asyncio.run(fire_alerts(pool, [EVENT])) == 2
    assert len(pool.history) == 2
    assert {(r["rule_id"], r["event_id"], r["action_type"]) for r in pool.history} == {
        ("r1", 11, "log"),
        ("r2", 11, "log"),
    }


def test_rescoring_the_same_event_fires_nothing() -> None:
    pool = FakePool([_rule("r1", "log")])

    assert asyncio.run(fire_alerts(pool, [EVENT])) == 1
    assert asyncio.run(fire_alerts(pool, [EVENT])) == 0
    assert len(pool.history) == 1


def test_the_same_event_twice_in_one_batch_fires_once() -> None:
    pool = FakePool([_rule("r1", "log")])

    assert asyncio.run(fire_alerts(pool, [EVENT, dict(EVENT)])) == 1
    assert len(pool.history) == 1


def test_one_rule_with_two_actions_fires_both() -> None:
    pool = FakePool([_rule("r1", "log", "webhook")])

    assert asyncio.run(fire_alerts(pool, [EVENT])) == 2
    assert {r["action_type"] for r in pool.history} == {"log", "webhook"}
    assert len(pool.history) == 2


def test_an_event_without_an_id_fires_on_every_call() -> None:
    pool = FakePool([_rule("r1", "log")])
    event = {k: v for k, v in EVENT.items() if k != "id"}

    assert asyncio.run(fire_alerts(pool, [event])) == 1
    assert asyncio.run(fire_alerts(pool, [event])) == 1
    assert len(pool.history) == 2
    assert all(r["event_id"] is None for r in pool.history)
