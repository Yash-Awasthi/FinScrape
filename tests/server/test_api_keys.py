"""Per-consumer API keys (plan m4.4): tiers, hashing, revocation, a real rate ceiling.

The plaintext key must exist only in the issue response; every stored row is a sha256
hex. The HTTP half runs against a fake pool, so no database is required.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server import db
from server.routes import keys

ADMIN = {"X-API-Key": "local-dev-key"}


class _Pool:
    """Just enough asyncpg: fetchrow/fetch/execute over an in-memory table."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append((sql, args))
        if sql.startswith("INSERT INTO consumer_keys"):
            row = {
                "id": args[0],
                "label": args[1],
                "tier": args[2],
                "key_hash": args[3],
                "key_prefix": args[4],
                "created_at": None,
                "last_used_at": None,
                "revoked_at": None,
            }
            self.rows[row["id"]] = row
            return row
        if sql.startswith("UPDATE consumer_keys SET last_used_at"):
            for row in self.rows.values():
                if row["key_hash"] == args[0] and row["revoked_at"] is None:
                    return row
            return None
        if sql.startswith("UPDATE consumer_keys SET revoked_at"):
            row = self.rows.get(args[0])
            if row is None:
                return None
            row["revoked_at"] = "2026-11-26T00:00:00+00:00"
            return {"id": row["id"], "revoked_at": row["revoked_at"]}
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def fetch(self, sql: str, *args):
        self.calls.append((sql, args))
        return list(self.rows.values())

    async def execute(self, sql: str, *args):
        self.calls.append((sql, args))
        return "UPDATE 1"

    def stored_text(self) -> str:
        return repr(self.rows) + repr(self.calls)


@pytest.fixture()
def pool(monkeypatch):
    fake = _Pool()
    monkeypatch.setattr(db, "pool", lambda: fake)
    keys.reset_rate_limits()
    yield fake
    keys.reset_rate_limits()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(keys.router)

    @app.get("/t/read", dependencies=[Depends(keys.require_consumer("read"))])
    async def read_probe() -> dict:
        return {"ok": True}

    @app.get("/t/write", dependencies=[Depends(keys.require_consumer("write"))])
    async def write_probe() -> dict:
        return {"ok": True}

    return app


@pytest.fixture()
def client(pool) -> TestClient:
    return TestClient(_app())


def _issue(client: TestClient, label: str = "partner", tier: str = "read") -> dict:
    response = client.post(
        "/api/admin/keys", json={"label": label, "tier": tier}, headers=ADMIN
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- hashing and issue -------------------------------------------------------


def test_the_plaintext_key_never_reaches_a_stored_row(client: TestClient, pool) -> None:
    body = _issue(client)
    raw = body["key"]
    assert raw.startswith("wfk_")
    assert len(raw) > 40
    assert raw not in pool.stored_text()
    assert keys.hash_key(raw) in pool.stored_text()


def test_two_issues_have_different_keys_and_hashes(client: TestClient, pool) -> None:
    first = _issue(client, "first")
    second = _issue(client, "second")
    assert first["key"] != second["key"]
    assert keys.hash_key(first["key"]) != keys.hash_key(second["key"])
    assert len(pool.rows) == 2


def test_issue_rejects_an_unknown_tier(client: TestClient, pool) -> None:
    response = client.post(
        "/api/admin/keys", json={"label": "x", "tier": "admin"}, headers=ADMIN
    )
    assert response.status_code == 400
    assert not pool.rows


def test_admin_routes_need_the_operator_key(client: TestClient) -> None:
    assert client.post("/api/admin/keys", json={"label": "x"}).status_code == 401
    assert client.get("/api/admin/keys").status_code == 401
    assert client.delete("/api/admin/keys/abc").status_code == 401


def test_list_never_leaks_a_hash_or_the_key(client: TestClient) -> None:
    body = _issue(client)
    listing = client.get("/api/admin/keys", headers=ADMIN).json()
    text = str(listing)
    assert "key_hash" not in text
    assert body["key"] not in text
    assert keys.hash_key(body["key"]) not in text
    assert listing["keys"][0]["key_prefix"] == body["key"][:12]


# --- authentication ----------------------------------------------------------


def test_a_live_key_can_call_the_dependency(client: TestClient) -> None:
    raw = _issue(client)["key"]
    assert client.get("/t/read", headers={"X-API-Key": raw}).status_code == 200


def test_an_unknown_key_is_401(client: TestClient) -> None:
    assert client.get("/t/read", headers={"X-API-Key": "wfk_wrong"}).status_code == 401


def test_a_revoked_key_is_401(client: TestClient) -> None:
    body = _issue(client)
    key_id = body["consumer"]["id"]
    assert client.delete(f"/api/admin/keys/{key_id}", headers=ADMIN).status_code == 200
    assert client.get("/t/read", headers={"X-API-Key": body["key"]}).status_code == 401


def test_revoking_twice_is_fine(client: TestClient) -> None:
    body = _issue(client)
    key_id = body["consumer"]["id"]
    first = client.delete(f"/api/admin/keys/{key_id}", headers=ADMIN)
    second = client.delete(f"/api/admin/keys/{key_id}", headers=ADMIN)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["revoked_at"] == second.json()["revoked_at"]


# --- tiers and the ceiling ---------------------------------------------------


def test_a_read_key_on_a_write_dependency_is_403(client: TestClient) -> None:
    raw = _issue(client, tier="read")["key"]
    assert client.get("/t/write", headers={"X-API-Key": raw}).status_code == 403
    assert client.get("/t/read", headers={"X-API-Key": raw}).status_code == 200


def test_a_write_key_passes_both(client: TestClient) -> None:
    raw = _issue(client, tier="write")["key"]
    assert client.get("/t/write", headers={"X-API-Key": raw}).status_code == 200


def test_the_sixty_first_read_in_a_minute_is_429_with_retry_after(
    client: TestClient,
) -> None:
    raw = _issue(client)["key"]
    for _ in range(keys.rate_limit("read")):
        assert client.get("/t/read", headers={"X-API-Key": raw}).status_code == 200
    over = client.get("/t/read", headers={"X-API-Key": raw})
    assert over.status_code == 429
    assert int(over.headers["Retry-After"]) >= 1
    assert keys.rate_limit("read") == 60
    assert keys.rate_limit("write") == 120
