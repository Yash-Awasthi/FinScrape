"""Alert rules in Postgres: load them, match new events, fire actions, log history.

Matching and sending stay in finscrape.alerts; this module owns only storage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import asyncpg

from finscrape.alerts import Action, AlertEngine, AlertRule, Condition

log = logging.getLogger("worldfin.alerts")


def _row_quiet_hours(row: asyncpg.Record | dict) -> dict:
    """A row without the column (or with NULL) is never quiet."""
    try:
        value = row["quiet_hours"]
    except KeyError, IndexError:
        return {}
    return value if isinstance(value, dict) else {}


def rule_from_row(row: asyncpg.Record | dict) -> AlertRule:
    return AlertRule(
        id=row["id"],
        name=row["name"],
        conditions=[Condition.from_dict(c) for c in row["conditions"]],
        actions=[Action.from_dict(a) for a in row["actions"]],
        enabled=row["enabled"],
        created_at=row["created_at"].isoformat(),
        quiet_hours=_row_quiet_hours(row),
    )


async def load_rules(pool: asyncpg.Pool) -> list[AlertRule]:
    rows = await pool.fetch(
        "SELECT id, name, conditions, actions, enabled, created_at, "
        "COALESCE(quiet_hours, '{}'::jsonb) AS quiet_hours "
        "FROM alert_rules ORDER BY created_at"
    )
    return [rule_from_row(r) for r in rows]


async def fire_alerts(pool: asyncpg.Pool, events: list[dict]) -> int:
    """Run every enabled rule over freshly inserted events. Returns actions fired."""
    rules = [
        r
        for r in await load_rules(pool)
        if r.enabled and not r.in_quiet_hours(datetime.now(UTC))
    ]
    if not rules or not events:
        return 0
    engine = AlertEngine(rules)
    # A (rule, event, action_type) key fires at most once, ever: re-scoring an
    # event must not repeat an action already recorded in alert_history.
    done: set[tuple[str, int, str]] = set()
    event_ids = [e["id"] for e in events if e.get("id") is not None]
    if event_ids:
        rows = await pool.fetch(
            "SELECT rule_id, event_id, action_type FROM alert_history "
            "WHERE event_id = ANY($1::bigint[])",
            event_ids,
        )
        done = {(r["rule_id"], r["event_id"], r["action_type"]) for r in rows}
    fired = 0
    for event in events:
        event_id = event.get("id")
        for rule, actions in engine.evaluate(event):
            pending = []
            for action in actions:
                if event_id is not None:
                    key = (rule.id, event_id, action.action_type)
                    if key in done:
                        continue
                    done.add(key)
                pending.append(action)
            if not pending:
                continue
            results = await asyncio.to_thread(engine.execute_actions, event, pending)
            await pool.executemany(
                "INSERT INTO alert_history (rule_id, event_id, action_type, status) "
                "VALUES ($1, $2, $3, $4)",
                [
                    (rule.id, event.get("id"), r["action_type"], r.get("status", "?"))
                    for r in results
                ],
            )
            fired += len(results)
    return fired
