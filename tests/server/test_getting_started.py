"""GET /docs/getting-started is a generated page, not a hand-copied one.

It must cover every path in the live contract, show one runnable curl per endpoint,
put the API key only on the operations that need it, and stay out of the schema that
`tests/snapshots/openapi.json` gates.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi.testclient import TestClient

from server import openapi_examples as examples


def _client() -> TestClient:
    from server.app import create_app

    return TestClient(create_app())


def _block(body: str, label: str) -> str:
    start = body.index(f"<h3>{label}</h3>")
    end = body.index("</code></pre>", start)
    return body[start:end]


def test_the_page_is_html_and_outside_the_contract():
    client = _client()
    response = client.get("/docs/getting-started")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/docs/getting-started" not in client.app.openapi()["paths"]
    assert "<html" in response.text


def test_one_curl_per_endpoint_grouped_by_path_prefix():
    client = _client()
    body = client.get("/docs/getting-started").text
    spec = client.app.openapi()
    operations = list(examples.iter_operations(spec))
    assert operations
    groups = {examples.folder_of(path) for path, _, _ in operations}
    for group in groups:
        assert f"<h2>{group}</h2>" in body
    assert body.count("curl -s ") >= len(operations)
    for path, method, _ in operations:
        assert f"<h3>{method.upper()} {path}</h3>" in body
    assert str(client.base_url).rstrip("/") in body


def test_the_api_key_is_shown_only_on_mutating_routes():
    body = _client().get("/docs/getting-started").text
    assert "X-API-Key" in _block(body, "POST /api/events")
    assert "X-API-Key" not in _block(body, "GET /api/events")
    assert "X-API-Key" not in _block(body, "GET /api/stats")
