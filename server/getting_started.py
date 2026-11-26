"""GET /docs/getting-started: every endpoint as a copy-paste curl, from the live schema.

Generated on each request from `app.openapi()`, so it cannot describe an endpoint the
API stopped serving. `include_in_schema=False` keeps it out of the contract that
`scripts/openapi_snapshot.py` gates: it is a reading aid, not an API surface.
"""

from __future__ import annotations

import html

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from server import openapi_examples as examples

_TITLE = "FinScrape API - getting started"
_KEY_EXPR = "${FINSCRAPE_API_KEY:-local-dev-key}"

# One line per group; the key is the segment `openapi_examples.folder_of` returns.
_NOTES = {
    "accuracy": "Scored outcomes: whether the call and the price move agreed.",
    "ai": "Model-backed analysis for one stored event; needs a configured LLM.",
    "alerts": "Alert rules. Reads are open; writes need the API key.",
    "candles": "OHLC candles for one symbol; the one endpoint here that requires a query parameter.",
    "correlations": "Co-movement signals across the recent event window.",
    "dates": "Days with at least one event; drives the dashboard calendar.",
    "events": "The feed, a single row, dashboard stats and the ingest path.",
    "feeds": "Configured RSS feeds and their health.",
    "health": "Liveness: always 200, degraded when the database is unreachable.",
    "market": "Live quotes; reaches the network.",
    "outcomes": "Individual scored predictions.",
    "predict": "Direction prediction for one stored event.",
    "ready": "Readiness: 200 only while the database answers.",
    "reliability": "Source reliability derived from scored outcomes.",
    "scenarios": "Clustered scenarios drawn from the event window.",
    "sectors": "Sector aggregates over the stored events.",
    "stats": "Dashboard counters the web app polls.",
    "storylines": "Related-event storylines.",
    "suggestions": "Ticker suggestions, one row per symbol.",
    "telegram": "Telegram webhook; authenticates with its own secret header.",
    "watchlists": "Named watchlists and the feed they produce.",
}


def render(spec: dict, base_url: str, *, api_key: str = _KEY_EXPR) -> str:
    """The whole page as one string; `spec` is an OpenAPI document."""
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    for path, method, op in examples.iter_operations(spec):
        groups.setdefault(examples.folder_of(path), []).append((path, method, op))

    sections = []
    for folder in sorted(groups):
        note = _NOTES.get(folder, f"Endpoints under /{folder}.")
        blocks = [
            f"<h3>{html.escape(f'{method.upper()} {path}')}</h3>\n"
            f"<pre><code>"
            f"{html.escape(examples.curl(spec, path, method, op, base_url, api_key=api_key))}"
            f"</code></pre>"
            for path, method, op in groups[folder]
        ]
        sections.append(
            f"<section>\n<h2>{html.escape(folder)}</h2>\n"
            f"<p>{html.escape(note)}</p>\n" + "\n".join(blocks) + "\n</section>"
        )

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(_TITLE)}</title>\n</head>\n<body>\n"
        f"<h1>{html.escape(_TITLE)}</h1>\n"
        f"<p>Every endpoint below, in curl form, generated from the live OpenAPI schema "
        f"at <code>{html.escape(base_url.rstrip('/') + '/openapi.json')}</code>. "
        f"Path parameters are shown with a sample value; optional query parameters are "
        f'listed at <a href="/docs">/docs</a>.</p>\n'
        f"<p>Mutating requests need <code>X-API-Key</code> "
        f"(or <code>Authorization: Bearer</code> with the same key). The commands read "
        f"<code>$FINSCRAPE_API_KEY</code> and fall back to the published development "
        f"key when it is unset.</p>\n"
        f"<p>The same requests are in <code>docs/postman.json</code>; regenerate it with "
        f"<code>python -m scripts.postman --write docs/postman.json</code>.</p>\n"
        + "\n".join(sections)
        + "\n</body>\n</html>\n"
    )


def install_getting_started(app: FastAPI) -> None:
    """Mount the page next to Swagger; it never appears in the contract."""

    @app.get(
        "/docs/getting-started",
        include_in_schema=False,
        response_class=HTMLResponse,
    )
    async def getting_started(request: Request) -> HTMLResponse:
        return HTMLResponse(render(request.app.openapi(), str(request.base_url)))
