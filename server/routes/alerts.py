"""Alert rule management: list, create, enable/disable, delete (mutations need the key)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from finscrape.alerts import Action, AlertRule, Condition
from server import db
from server.alert_rules import load_rules
from server.auth import require_api_key

router = APIRouter()

_HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _quiet_hours(raw: object) -> dict:
    """{"start": "HH:MM", "end": "HH:MM"} in UTC, or {} for no window."""
    if raw is None or raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="quiet_hours must be an object")
    extra = set(raw) - {"start", "end"}
    if extra:
        raise HTTPException(
            status_code=400, detail="quiet_hours accepts only start and end"
        )
    start, end = raw.get("start"), raw.get("end")
    if not (
        isinstance(start, str)
        and isinstance(end, str)
        and _HHMM.match(start)
        and _HHMM.match(end)
    ):
        raise HTTPException(
            status_code=400, detail="quiet_hours start and end must be HH:MM (UTC)"
        )
    return {"start": start, "end": end}


@router.get("/api/alerts/rules")
async def list_rules() -> dict:
    return {"rules": [r.to_dict() for r in await load_rules(db.pool())]}


@router.post("/api/alerts/rules", dependencies=[Depends(require_api_key)])
async def add_rule(payload: dict = Body(...)) -> dict:
    """Body: {name, conditions: [{field, operator, value}], actions?: [{action_type, config}], quiet_hours?: {start, end}}."""
    quiet_hours = _quiet_hours(payload.get("quiet_hours"))
    try:
        rule = AlertRule(
            name=str(payload.get("name") or "").strip(),
            conditions=[
                Condition.from_dict(c) for c in payload.get("conditions") or []
            ],
            actions=[Action.from_dict(a) for a in payload.get("actions") or []]
            or [Action(action_type="log")],
            quiet_hours=quiet_hours,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid rule: {exc}")
    if not rule.name or not rule.conditions:
        raise HTTPException(status_code=400, detail="name and conditions required")
    await db.pool().execute(
        "INSERT INTO alert_rules (id, name, conditions, actions, quiet_hours) "
        "VALUES ($1, $2, $3, $4, $5)",
        rule.id,
        rule.name,
        [c.to_dict() for c in rule.conditions],
        [a.to_dict() for a in rule.actions],
        rule.quiet_hours,
    )
    return {"ok": True, "rule": rule.to_dict()}


@router.patch("/api/alerts/rules/{rule_id}", dependencies=[Depends(require_api_key)])
async def set_enabled(rule_id: str, payload: dict = Body(...)) -> dict:
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled must be true or false")
    status = await db.pool().execute(
        "UPDATE alert_rules SET enabled = $2 WHERE id = $1", rule_id, enabled
    )
    return {"ok": status != "UPDATE 0", "id": rule_id, "enabled": enabled}


@router.delete("/api/alerts/rules/{rule_id}", dependencies=[Depends(require_api_key)])
async def delete_rule(rule_id: str) -> dict:
    status = await db.pool().execute("DELETE FROM alert_rules WHERE id = $1", rule_id)
    return {"ok": status != "DELETE 0", "id": rule_id}


# The notification centre (plan m4.3.1): what the rules fired, newest first, with the
# event each row refers to. The mark lives in alert_history.read_at (migration 0020).
_NOTIFICATIONS = (
    "SELECT h.id, h.rule_id, r.name AS rule_name, h.event_id, e.subject AS event_subject, "
    "e.verdict AS event_verdict, e.timestamp AS event_timestamp, h.action_type, h.status, "
    "h.fired_at, h.read_at IS NOT NULL AS is_read "
    "FROM alert_history h "
    "LEFT JOIN alert_rules r ON r.id = h.rule_id "
    "LEFT JOIN events e ON e.id = h.event_id "
    "ORDER BY h.fired_at DESC, h.id DESC LIMIT $1"
)


@router.get("/api/alerts/notifications")
async def notifications(limit: int = Query(50, ge=1)) -> dict:
    """The last N fired alerts; default 50, capped at 50. Reads need no key."""
    rows = await db.pool().fetch(_NOTIFICATIONS, min(limit, 50))
    items = [
        {
            "id": r["id"],
            "rule_id": r["rule_id"],
            "rule_name": r["rule_name"],
            "event_id": r["event_id"],
            "event_subject": r["event_subject"],
            "event_verdict": r["event_verdict"],
            "event_timestamp": r["event_timestamp"].isoformat()
            if r["event_timestamp"] is not None
            else None,
            "action_type": r["action_type"],
            "status": r["status"],
            "fired_at": r["fired_at"].isoformat(),
            "read": bool(r["is_read"]),
        }
        for r in rows
    ]
    return {
        "notifications": items,
        "unread": sum(1 for item in items if not item["read"]),
    }


@router.patch(
    "/api/alerts/notifications/{notification_id}",
    dependencies=[Depends(require_api_key)],
)
async def set_notification_read(
    notification_id: int, payload: dict = Body(...)
) -> dict:
    """Mark one fired alert read or unread; only the mark changes."""
    read = payload.get("read")
    if not isinstance(read, bool):
        raise HTTPException(status_code=400, detail="read must be true or false")
    status = await db.pool().execute(
        "UPDATE alert_history SET read_at = CASE WHEN $2 THEN now() ELSE NULL END "
        "WHERE id = $1",
        notification_id,
        read,
    )
    if status == "UPDATE 0":
        raise HTTPException(status_code=404, detail="no such notification")
    return {"ok": True, "id": notification_id, "read": read}
