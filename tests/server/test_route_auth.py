"""Every mutating route is authenticated, and the set is exactly the documented one.

plan M1.6: the API is read-only by design, so a new POST/PATCH/DELETE that forgets its
guard is the whole attack surface. This enumerates the real app and fails on any mutating
route that is neither behind `require_api_key` nor behind Telegram's webhook secret.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.app import create_app
from server.settings import DEFAULT_API_KEY, get_settings

READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# The documented guard set: four routes take the API key…
API_KEY_ROUTES = {
    ("POST", "/api/events"),
    ("POST", "/api/alerts/rules"),
    ("PATCH", "/api/alerts/rules/{rule_id}"),
    ("DELETE", "/api/alerts/rules/{rule_id}"),
    ("PATCH", "/api/alerts/notifications/{notification_id}"),
    ("POST", "/api/admin/keys"),
    ("DELETE", "/api/admin/keys/{key_id}"),
    ("POST", "/api/watchlists"),
    ("POST", "/api/watchlists/{watchlist_id}/items"),
    ("DELETE", "/api/watchlists/{watchlist_id}/items/{item_id}"),
    ("DELETE", "/api/watchlists/{watchlist_id}"),
}
# …and the Telegram webhook authenticates with its own secret header on every call
# (it must answer 200 to a bad sender, so it cannot 401 like the others).
WEBHOOK_ROUTES = {("POST", "/api/telegram/webhook")}


def _api_routes(app) -> list[APIRoute]:
    """Flatten the app: FastAPI 0.143 keeps an `_IncludedRouter` wrapper per router."""
    out: list[APIRoute] = []
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        inner = getattr(route, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
        elif isinstance(route, APIRoute):
            out.append(route)
    return out


def _mutating() -> list[tuple[str, str, APIRoute]]:
    app = create_app()
    return [
        (method, route.path, route)
        for route in _api_routes(app)
        for method in route.methods - READ_METHODS
    ]


def _guards(route: APIRoute) -> set[str]:
    return {d.call.__name__ for d in route.dependant.dependencies}


def test_the_mutating_surface_matches_what_the_openapi_schema_publishes():
    # Two independent views of the same contract: the route objects and the schema.
    published = {
        (method.upper(), path)
        for path, ops in create_app().openapi()["paths"].items()
        for method in ops
        if method.upper() not in READ_METHODS
    }
    assert (
        published
        == {(m, p) for m, p, _ in _mutating()}
        == API_KEY_ROUTES | WEBHOOK_ROUTES
    )


def test_every_api_route_that_can_write_is_behind_the_api_key():
    unguarded = [
        f"{method} {path}"
        for method, path, route in _mutating()
        if (method, path) in API_KEY_ROUTES and "require_api_key" not in _guards(route)
    ]
    assert not unguarded, unguarded


def test_every_mutating_route_has_some_guard():
    # Belt and braces: even a route added to the allowlists above must carry one.
    naked = [
        f"{method} {path} guards={sorted(_guards(route))}"
        for method, path, route in _mutating()
        if not _guards(route) and (method, path) not in WEBHOOK_ROUTES
    ]
    assert not naked, naked


def test_no_mutating_route_answers_200_without_the_key(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setenv("WORLDFIN_RATE_LIMIT_PER_MIN", "0")  # 429s would mask a 401
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        for method, path in sorted(API_KEY_ROUTES):
            url = (
                path.replace("{rule_id}", "1")
                .replace("{notification_id}", "1")
                .replace("{key_id}", "1")
            )
            resp = client.request(method, url, json={})
            assert resp.status_code == 401, (method, url, resp.status_code)
        # The webhook cannot 401 by design; a bad secret must still do nothing.
        resp = client.post(
            "/api/telegram/webhook", json={"message": {"text": "/today"}}
        )
        assert resp.status_code == 200 and resp.json() == {"ok": True}
    finally:
        get_settings.cache_clear()


def test_the_published_default_key_is_the_only_one_that_works_out_of_the_box():
    # The documented default is public; this pins the fact that it is, so
    # `uses_default_api_key` (and the production refusal) cannot drift from it.
    get_settings.cache_clear()
    assert get_settings().api_key == DEFAULT_API_KEY
    get_settings.cache_clear()
