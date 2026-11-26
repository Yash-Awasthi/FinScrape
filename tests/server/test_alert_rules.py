"""The weekly digest and the notification centre (plan m4.3.1, m4.3.2).

Pure: no database, no network; the digest CLI runs in a subprocess and the notification
route runs over a fake pool so its own assertions always execute.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from server.alerts_digest import DISCLAIMER, build_digest, markdown_to_pdf

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "DIGEST.md"
HEADINGS = [
    "Window",
    "Calls scored",
    "Hit rate",
    "By verdict",
    "Best call",
    "Worst call",
    "Disclaimer",
]


def _record(**overrides) -> dict:
    record = {
        "window": {
            "from": "2026-11-02T00:00:00+00:00",
            "to": "2026-11-27T00:00:00+00:00",
        },
        "total": 12,
        "scored": 8,
        "n": 8,
        "hits": 5,
        "hit_rate": 0.625,
        "ci95": [0.306, 0.863],
        "by_verdict": {
            "INVEST": {
                "hits": 3,
                "total": 5,
                "hit_rate": 0.6,
                "n": 5,
                "ci95": [0.231, 0.882],
            },
            "PULL_OUT": {
                "hits": 2,
                "total": 3,
                "hit_rate": 0.667,
                "n": 3,
                "ci95": [0.208, 0.939],
            },
        },
        "best": {
            "subject": "Apple",
            "verdict": "INVEST",
            "move": 12.3,
            "at": "2026-11-10T09:00:00+00:00",
        },
        "worst": {
            "subject": "Boeing",
            "verdict": "PULL_OUT",
            "move": -4.5,
            "at": "2026-11-12T09:00:00+00:00",
        },
    }
    record.update(overrides)
    return record


def _headings(md: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", md, re.MULTILINE)]


def test_sections_appear_in_the_planned_order() -> None:
    md = build_digest(_record())
    positions = [md.index(f"## {name}") for name in HEADINGS]

    assert positions == sorted(positions)
    assert _headings(md) == HEADINGS


def test_hit_rate_carries_n_and_the_interval() -> None:
    md = build_digest(_record())

    assert "n=8" in md
    assert "30.6%" in md
    assert "86.3%" in md


def test_hit_rate_says_so_when_the_interval_is_missing() -> None:
    md = build_digest(_record(ci95=None))

    assert "n=8" in md
    assert "interval not recorded" in md


def test_pdf_is_real_and_greppable() -> None:
    pdf = markdown_to_pdf(build_digest(_record()))

    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF")
    assert b"Weekly digest" in pdf
    marker = pdf.rindex(b"startxref")
    offset = int(pdf[marker + len(b"startxref") :].split()[0])
    assert pdf[offset : offset + 4] == b"xref"


def test_template_lists_every_heading_the_code_emits() -> None:
    from_template = _headings(DOCS.read_text(encoding="utf-8"))
    from_digest = _headings(build_digest(_record()))

    assert from_template == from_digest
    for name in from_template:
        assert f"## {name}" in build_digest(_record())


def test_cli_writes_markdown_and_pdf(tmp_path: Path) -> None:
    fixture = tmp_path / "record.json"
    fixture.write_text(json.dumps(_record()), encoding="utf-8")
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "server.alerts_digest",
            "--fixture",
            str(fixture),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    md_path = out / "digest-2026-W48.md"
    pdf_path = out / "digest-2026-W48.pdf"
    assert md_path.is_file()
    assert pdf_path.is_file()
    assert DISCLAIMER in md_path.read_text(encoding="utf-8")
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert str(md_path) in result.stdout
    assert str(pdf_path) in result.stdout


# --- notification centre (plan m4.3.1) ---------------------------------------


def _notification(rows: list[dict]):
    """The route with a fake pool: no database, the real handler and the real SQL."""
    pytest.importorskip("asyncpg")
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server import db
    from server.routes import alerts

    class _Pool:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple]] = []

        async def fetch(self, sql: str, *args):
            self.calls.append((sql, args))
            return rows

    pool = _Pool()
    app = FastAPI()
    app.include_router(alerts.router)
    return pool, app, TestClient, db


def _row(day: int, *, read: bool = False) -> dict:
    from datetime import UTC, datetime

    return {
        "id": day,
        "rule_id": "r1",
        "rule_name": "Energy shock",
        "event_id": 100 + day,
        "event_subject": f"Story {day}",
        "event_verdict": "INVEST",
        "event_timestamp": datetime(2026, 11, day, tzinfo=UTC),
        "action_type": "telegram",
        "status": "sent",
        "fired_at": datetime(2026, 11, day, 4, tzinfo=UTC),
        "is_read": read,
    }


def test_notifications_joins_the_event_and_counts_unread(monkeypatch) -> None:
    pool, app, TestClient, db = _notification([_row(26), _row(25, read=True), _row(24)])
    monkeypatch.setattr(db, "pool", lambda: pool)

    response = TestClient(app).get("/api/alerts/notifications")

    assert response.status_code == 200
    body = response.json()
    assert body["unread"] == 2
    first = body["notifications"][0]
    assert first == {
        "id": 26,
        "rule_id": "r1",
        "rule_name": "Energy shock",
        "event_id": 126,
        "event_subject": "Story 26",
        "event_verdict": "INVEST",
        "event_timestamp": "2026-11-26T00:00:00+00:00",
        "action_type": "telegram",
        "status": "sent",
        "fired_at": "2026-11-26T04:00:00+00:00",
        "read": False,
    }
    assert body["notifications"][1]["read"] is True
    # Newest first is the SQL's job, and the SQL says so.
    assert "ORDER BY h.fired_at DESC" in pool.calls[0][0]


def test_notifications_defaults_to_50_and_clamps_the_limit(monkeypatch) -> None:
    pool, app, TestClient, db = _notification([])
    monkeypatch.setattr(db, "pool", lambda: pool)
    client = TestClient(app)

    client.get("/api/alerts/notifications")
    client.get("/api/alerts/notifications?limit=7")
    client.get("/api/alerts/notifications?limit=500")

    assert [call[1][0] for call in pool.calls] == [50, 7, 50]


def test_notifications_need_no_api_key(monkeypatch) -> None:
    pool, app, TestClient, db = _notification([_row(26)])
    monkeypatch.setattr(db, "pool", lambda: pool)

    response = TestClient(app).get("/api/alerts/notifications")

    assert response.status_code == 200


def _notification_patch(status: str = "UPDATE 1"):
    """The same route with a pool that records the UPDATE and answers `status`."""
    pytest.importorskip("asyncpg")
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server import db
    from server.routes import alerts
    from server.settings import get_settings

    class _Pool:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple]] = []

        async def fetch(self, sql: str, *args):
            return []

        async def execute(self, sql: str, *args):
            self.executed.append((sql, args))
            return status

    pool = _Pool()
    app = FastAPI()
    app.include_router(alerts.router)
    return pool, app, TestClient, db, get_settings


def _patch(client, pool, body: dict, key: str | None = "operator-chosen"):
    headers = {"X-API-Key": key} if key else {}
    return client.patch("/api/alerts/notifications/26", json=body, headers=headers)


def test_marking_read_writes_now_and_returns_the_mark(monkeypatch) -> None:
    pool, app, TestClient, db, get_settings = _notification_patch()
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setattr(db, "pool", lambda: pool)
    get_settings.cache_clear()
    try:
        response = _patch(TestClient(app), pool, {"read": True})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": 26, "read": True}
    sql, args = pool.executed[0]
    assert "read_at = CASE WHEN $2 THEN now() ELSE NULL END" in sql
    assert args == (26, True)


def test_unreading_clears_the_mark(monkeypatch) -> None:
    pool, app, TestClient, db, get_settings = _notification_patch()
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setattr(db, "pool", lambda: pool)
    get_settings.cache_clear()
    try:
        response = _patch(TestClient(app), pool, {"read": False})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["read"] is False
    assert pool.executed[0][1] == (26, False)


def test_the_mark_needs_the_api_key(monkeypatch) -> None:
    pool, app, TestClient, db, get_settings = _notification_patch()
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setattr(db, "pool", lambda: pool)
    get_settings.cache_clear()
    try:
        response = _patch(TestClient(app), pool, {"read": True}, key=None)
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert pool.executed == []


def test_a_non_bool_mark_is_400(monkeypatch) -> None:
    pool, app, TestClient, db, get_settings = _notification_patch()
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setattr(db, "pool", lambda: pool)
    get_settings.cache_clear()
    try:
        response = _patch(TestClient(app), pool, {"read": "yes"})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "read must be true or false"
    assert pool.executed == []


def test_an_unknown_notification_is_404(monkeypatch) -> None:
    pool, app, TestClient, db, get_settings = _notification_patch(status="UPDATE 0")
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setattr(db, "pool", lambda: pool)
    get_settings.cache_clear()
    try:
        response = _patch(TestClient(app), pool, {"read": True})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404
