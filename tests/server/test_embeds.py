"""Embeddable widget (plan m4.4): one iframe, one allowed parent, no wildcard.

The security claim is the test: `frame-ancestors` must name the exact origin asked for,
plain http is for localhost only, and the widget's script is loaded from self so the CSP
never needs `'unsafe-inline'`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes import keys

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; "
    "script-src 'self'; frame-ancestors {origin}; base-uri 'none'"
)


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(keys.router)
    return TestClient(app)


def _csp(response) -> str:
    return response.headers["Content-Security-Policy"]


def test_frame_ancestors_is_exactly_the_parent_origin(client: TestClient) -> None:
    response = client.get(
        "/embed/track-record", params={"parent": "https://example.com"}
    )
    assert response.status_code == 200
    assert _csp(response) == CSP.format(origin="https://example.com")
    assert "frame-ancestors https://example.com;" in _csp(response)
    assert "frame-ancestors *" not in _csp(response)


def test_a_port_and_a_subdomain_are_kept_verbatim(client: TestClient) -> None:
    response = client.get(
        "/embed/track-record", params={"parent": "https://news.example.com:8443"}
    )
    assert response.status_code == 200
    assert "frame-ancestors https://news.example.com:8443;" in _csp(response)


def test_localhost_http_is_allowed_for_development(client: TestClient) -> None:
    response = client.get(
        "/embed/track-record", params={"parent": "http://localhost:3000"}
    )
    assert response.status_code == 200
    assert "frame-ancestors http://localhost:3000;" in _csp(response)


@pytest.mark.parametrize(
    "parent",
    [
        None,
        "",
        "example.com",
        "http://example.com",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://*",
        "https://user:pass@example.com",
        "ftp://example.com",
    ],
)
def test_an_unusable_parent_is_400_plain_text(client: TestClient, parent) -> None:
    params = {} if parent is None else {"parent": parent}
    response = client.get("/embed/track-record", params=params)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/plain")
    assert "parent" in response.text


def test_an_unknown_widget_is_404(client: TestClient) -> None:
    response = client.get("/embed/nope", params={"parent": "https://example.com"})
    assert response.status_code == 404


def test_a_scenario_widget_needs_an_id(client: TestClient) -> None:
    response = client.get("/embed/scenario", params={"parent": "https://example.com"})
    assert response.status_code == 400


def test_the_scenario_id_reaches_the_widget_markup(client: TestClient) -> None:
    response = client.get(
        "/embed/scenario",
        params={"id": "s42", "parent": "https://example.com"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'data-kind="scenario"' in response.text
    assert 'data-id="s42"' in response.text
    assert "/app/scenario/s42" in response.text
    assert "not financial advice" in response.text


def test_the_csp_does_not_allow_inline_script(client: TestClient) -> None:
    response = client.get(
        "/embed/track-record", params={"parent": "https://example.com"}
    )
    csp = _csp(response)
    script = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'self'" in script
    assert "unsafe-inline" not in script
    assert "unsafe-eval" not in script
    # The widget's script is a same-origin file, not an inline block.
    assert '<script src="/embed/widget.js"' in response.text


def test_x_frame_options_is_absent_on_purpose(client: TestClient) -> None:
    response = client.get(
        "/embed/track-record", params={"parent": "https://example.com"}
    )
    assert "X-Frame-Options" not in response.headers


def test_the_script_route_serves_javascript(client: TestClient) -> None:
    response = client.get("/embed/widget.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "/api/scenarios/" in response.text
    assert "/api/accuracy" in response.text


def test_the_real_app_mounts_the_widget() -> None:
    pytest.importorskip("pydantic_settings")
    from server.app import create_app

    response = TestClient(create_app()).get(
        "/embed/track-record", params={"parent": "https://example.com"}
    )
    assert response.status_code == 200
    assert "frame-ancestors https://example.com;" in _csp(response)
