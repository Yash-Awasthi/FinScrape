"""Alert rule management: list, create, enable/disable, delete (mutations need the key)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from finscrape.alerts import Action, AlertRule, Condition
from server import db
from server.alert_rules import load_rules
from server.auth import require_api_key

router = APIRouter()


@router.get("/api/alerts/rules")
async def list_rules() -> dict:
    return {"rules": [r.to_dict() for r in await load_rules(db.pool())]}


@router.post("/api/alerts/rules", dependencies=[Depends(require_api_key)])
async def add_rule(payload: dict = Body(...)) -> dict:
    """Body: {name, conditions: [{field, operator, value}], actions?: [{action_type, config}]}."""
    try:
        rule = AlertRule(
            name=str(payload.get("name") or "").strip(),
            conditions=[
                Condition.from_dict(c) for c in payload.get("conditions") or []
            ],
            actions=[Action.from_dict(a) for a in payload.get("actions") or []]
            or [Action(action_type="log")],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid rule: {exc}")
    if not rule.name or not rule.conditions:
        raise HTTPException(status_code=400, detail="name and conditions required")
    await db.pool().execute(
        "INSERT INTO alert_rules (id, name, conditions, actions) VALUES ($1, $2, $3, $4)",
        rule.id,
        rule.name,
        [c.to_dict() for c in rule.conditions],
        [a.to_dict() for a in rule.actions],
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
