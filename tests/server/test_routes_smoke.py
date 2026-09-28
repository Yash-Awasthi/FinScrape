"""Every DB-backed read route answers against a real Postgres.

`_SUGGESTIONS_SQL` shipped green with `r.subject` resolved against `ticker_stats`,
a CTE that has no event columns — asyncpg raises UndefinedColumnError at prepare
time, so `/api/suggestions` was a 500 on every call regardless of data. Unit tests
stub the pool, so only a live connection catches that class of defect.

Routes that leave the process (market data, LLM, RSS) are excluded: they fail on
the network, not on our SQL.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("asyncpg")

from tests.server import PG_DSN, pg_reachable

pytestmark = pytest.mark.skipif(
    not pg_reachable(), reason="no Postgres at WORLDFIN_TEST_DATABASE_URL"
)

# Reach outside the process, so a failure here is not a SQL defect.
_EXTERNAL = {
    "/api/agents/analyze",
    "/api/ai/analyze",
    "/api/ai/council",
    "/api/candles",
    "/api/markets",
    "/api/quotes",
    "/api/rss-proxy",
    "/api/scenarios",
    "/api/sentiment",
    "/api/storylines",
    "/api/v1/geopolitical/alerts",
    "/api/v1/geopolitical/dashboard",
    "/api/v1/geopolitical/global-risk",
    "/api/v1/geopolitical/regions",
    "/api/v1/geopolitical/top-risks",
    "/api/v1/sentiment/divergences",
    "/api/v1/sentiment/extremes",
    "/api/v1/sentiment/market/overview",
}


def _db_backed_paths(app) -> list[str]:
    spec = app.openapi()
    return sorted(
        path
        for path, ops in spec["paths"].items()
        if "get" in ops
        and path.startswith("/api/")
        and "{" not in path  # needs an id we cannot invent
        and path not in _EXTERNAL
    )


@pytest.fixture(scope="module")
def client(monkeypatch_module=None):
    import os

    os.environ["WORLDFIN_DATABASE_URL"] = PG_DSN
    from server.main import app
    from server.settings import get_settings

    # An earlier test may have cached settings built before the DSN was set.
    get_settings.cache_clear()

    with TestClient(app) as c:
        yield c


def test_db_backed_get_routes_do_not_500(client):
    paths = _db_backed_paths(client.app)
    assert paths, "route discovery found nothing — the filter is wrong"
    failures = []
    for path in paths:
        response = client.get(path)
        if response.status_code >= 500:
            failures.append(f"{path} -> {response.status_code} {response.text[:200]}")
    assert not failures, "DB-backed routes returned 5xx:\n" + "\n".join(failures)


def test_suggestions_returns_the_newest_event_per_ticker(client):
    """The columns the broken SQL could not resolve are the ones the SPA reads."""
    response = client.get("/api/suggestions", params={"limit": 5})
    assert response.status_code == 200
    for suggestion in response.json()["suggestions"]:
        assert {
            "ticker",
            "score",
            "mentions",
            "latest_subject",
            "latest_verdict",
            "sector",
        } <= set(suggestion)


def test_scenario_columns_query_prepares() -> None:
    """`/api/scenarios` is excluded above (it embeds via Ollama), so its SQL still
    needs a prepare check of its own."""
    import asyncpg

    from server.routes.insight import _SCENARIO_COLUMNS

    async def _prepare() -> None:
        conn = await asyncpg.connect(PG_DSN)
        try:
            await conn.prepare(_SCENARIO_COLUMNS)
        finally:
            await conn.close()

    asyncio.run(_prepare())
