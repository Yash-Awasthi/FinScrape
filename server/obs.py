"""Phase 9 observability: Prometheus metrics + request-id/latency middleware.

One module owns every metric so both processes (API + worker) register the same
series. Counters/histograms are incremented at the event site (ingest, LLM call,
HTTP request); point-in-time gauges (WS clients, source freshness) are refreshed
inside the /metrics handler at scrape time. The worker exposes its own /metrics via
prometheus_client.start_http_server (worker/main.py); the API mounts the route below.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

from finscrape.logging_config import correlation_id

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("worldfin.obs")

# --- metric definitions (registered once, on the default registry) ----------
EVENTS_INGESTED = Counter(
    "worldfin_events_ingested_total", "Events written to the DB", ["source"]
)
EVENTS_DUPLICATE = Counter(
    "worldfin_events_duplicate_total", "Events skipped as duplicates", ["source"]
)
SOURCE_CYCLES = Counter(
    "worldfin_source_cycles_total", "Worker source cycles", ["source", "status"]
)
LLM_LATENCY = Histogram(
    "worldfin_llm_request_seconds",
    "LLM chat-completion latency",
    ["backend", "outcome"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)
HTTP_REQUESTS = Counter(
    "worldfin_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "worldfin_http_request_seconds", "HTTP request latency", ["method", "path"]
)
WS_CLIENTS = Gauge("worldfin_ws_clients", "Connected WebSocket clients")
SOURCE_AGE = Gauge(
    "worldfin_source_age_seconds", "Seconds since a source last fetched", ["source"]
)
SOURCE_UP = Gauge(
    "worldfin_source_up", "1 if the source is fresh and OK, else 0", ["source"]
)


@contextmanager
def time_llm(backend: str):
    """Time one LLM call; record latency + outcome (ok|error). Never swallows."""
    start = time.monotonic()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        LLM_LATENCY.labels(backend=backend, outcome=outcome).observe(
            time.monotonic() - start
        )


def record_ingest(source: str, inserted: int, duplicates: int, status: str) -> None:
    """Bump ingest counters from the worker after one source cycle."""
    if inserted:
        EVENTS_INGESTED.labels(source=source).inc(inserted)
    if duplicates:
        EVENTS_DUPLICATE.labels(source=source).inc(duplicates)
    SOURCE_CYCLES.labels(source=source, status=status).inc()


def install_observability(app: FastAPI, stale_after_min: int = 60) -> None:
    """Mount /metrics and the outermost request-id + latency middleware.

    fastapi/prometheus serialization imports are local so the worker (which imports
    the metric helpers above) never needs fastapi installed."""
    from fastapi import Request
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        cid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = correlation_id.set(cid)
        start = time.monotonic()
        try:
            resp = await call_next(request)
            status = resp.status_code
        finally:
            # Bound cardinality: use the matched route template, not the raw path.
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            method = request.method
            HTTP_LATENCY.labels(method=method, path=path).observe(
                time.monotonic() - start
            )
            correlation_id.reset(token)
        HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
        resp.headers["X-Request-ID"] = cid
        return resp

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        # Refresh point-in-time gauges right before serializing.
        from server import db
        from server.ws import hub

        WS_CLIENTS.set(hub.count)
        try:
            rows = await db.pool().fetch(
                "SELECT source, status, "
                "EXTRACT(EPOCH FROM (now() - fetched_at)) AS age "
                "FROM source_health"
            )
            for r in rows:
                age = float(r["age"])
                SOURCE_AGE.labels(source=r["source"]).set(age)
                fresh = r["status"] == "OK" and age <= stale_after_min * 60
                SOURCE_UP.labels(source=r["source"]).set(1 if fresh else 0)
        # Metrics still serve on a broken DB.
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            log.warning("metrics: source freshness query failed: %s", exc)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
