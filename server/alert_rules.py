"""Alert rules in Postgres: load them, match new events, fire actions, log history.

Matching and sending stay in finscrape.alerts; this module owns only storage.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from finscrape.alerts import Action, AlertEngine, AlertRule, Condition

log = logging.getLogger("worldfin.alerts")


def rule_from_row(row: asyncpg.Record | dict) -> AlertRule:
    return AlertRule(
        id=row["id"],
        name=row["name"],
        conditions=[Condition.from_dict(c) for c in row["conditions"]],
        actions=[Action.from_dict(a) for a in row["actions"]],
        enabled=row["enabled"],
        created_at=row["created_at"].isoformat(),
    )


async def load_rules(pool: asyncpg.Pool) -> list[AlertRule]:
    rows = await pool.fetch(
        "SELECT id, name, conditions, actions, enabled, created_at "
        "FROM alert_rules ORDER BY created_at"
    )
    return [rule_from_row(r) for r in rows]


async def fire_alerts(pool: asyncpg.Pool, events: list[dict]) -> int:
    """Run every enabled rule over freshly inserted events. Returns actions fired."""
    rules = [r for r in await load_rules(pool) if r.enabled]
    if not rules or not events:
        return 0
    engine = AlertEngine(rules)
    fired = 0
    for event in events:
        for rule, actions in engine.evaluate(event):
            results = await asyncio.to_thread(engine.execute_actions, event, actions)
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
