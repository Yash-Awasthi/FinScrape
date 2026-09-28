"""Phase 9 observability: JSON logging, correlation ids, Prometheus metrics.

Pure/unit where possible; the /metrics + request-id middleware are exercised on a
throwaway app (no DB — the freshness query is caught and skipped), mirroring the
hardening tests.
"""

from __future__ import annotations

import json
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("prometheus_client")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from finscrape.logging_config import (
    JsonFormatter,
    correlation_id,
    setup_logging,
)
from server import obs


def _record(msg: str = "hello %s", args=("world",), **extra) -> logging.LogRecord:
    rec = logging.LogRecord("worldfin.x", logging.INFO, "f.py", 1, msg, args, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


# --- JSON logging -----------------------------------------------------------


def test_json_formatter_emits_valid_json_with_message_and_extras():
    token = correlation_id.set("cid-123")
    try:
        out = JsonFormatter().format(_record(source="gdelt", stage="ingest"))
    finally:
        correlation_id.reset(token)
    d = json.loads(out)
    assert d["msg"] == "hello world"
    assert d["level"] == "INFO"
    assert d["logger"] == "worldfin.x"
    assert d["correlation_id"] == "cid-123"
    assert d["source"] == "gdelt" and d["stage"] == "ingest"
    assert "ts" in d


def test_json_formatter_omits_correlation_id_when_unset():
    # contextvar default is empty -> no key (avoid noisy empty fields)
    assert correlation_id.get() == ""
    d = json.loads(JsonFormatter().format(_record()))
    assert "correlation_id" not in d


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record("failed", args=())
        rec.exc_info = sys.exc_info()
    d = json.loads(JsonFormatter().format(rec))
    assert "ValueError: boom" in d["exc"]


def test_setup_logging_json_toggle_picks_formatter():
    setup_logging(json_format=True)
    root = logging.getLogger()
    assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
    # idempotent: no handler pile-up on repeat calls
    n = len(root.handlers)
    setup_logging(json_format=True)
    assert len(root.handlers) == n
    setup_logging(json_format=False)  # restore human format for other tests


# --- metric helpers ---------------------------------------------------------


def test_record_ingest_increments_counters():
    obs.record_ingest("srcA", inserted=3, duplicates=2, status="OK")
    assert (
        REGISTRY.get_sample_value("worldfin_events_ingested_total", {"source": "srcA"})
        == 3
    )
    assert (
        REGISTRY.get_sample_value("worldfin_events_duplicate_total", {"source": "srcA"})
        == 2
    )
    assert (
        REGISTRY.get_sample_value(
            "worldfin_source_cycles_total", {"source": "srcA", "status": "OK"}
        )
        == 1
    )


def test_time_llm_records_ok_and_error_outcomes():
    with obs.time_llm("backendX"):
        pass
    assert (
        REGISTRY.get_sample_value(
            "worldfin_llm_request_seconds_count",
            {"backend": "backendX", "outcome": "ok"},
        )
        == 1
    )
    with pytest.raises(ValueError), obs.time_llm("backendX"):
        raise ValueError("nope")
    assert (
        REGISTRY.get_sample_value(
            "worldfin_llm_request_seconds_count",
            {"backend": "backendX", "outcome": "error"},
        )
        == 1
    )


# --- /metrics + request-id middleware ---------------------------------------


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    obs.install_observability(app)
    return app


def test_metrics_endpoint_exposes_prometheus_text():
    client = TestClient(_app())
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "worldfin_http_requests_total" in r.text


def test_request_id_generated_and_echoed():
    client = TestClient(_app())
    # generated when absent
    r = client.get("/ping")
    assert r.headers.get("X-Request-ID")
    # echoed when provided
    r2 = client.get("/ping", headers={"X-Request-ID": "trace-abc"})
    assert r2.headers["X-Request-ID"] == "trace-abc"


def test_http_request_counter_increments():
    client = TestClient(_app())
    before = (
        REGISTRY.get_sample_value(
            "worldfin_http_requests_total",
            {"method": "GET", "path": "/ping", "status": "200"},
        )
        or 0
    )
    client.get("/ping")
    after = REGISTRY.get_sample_value(
        "worldfin_http_requests_total",
        {"method": "GET", "path": "/ping", "status": "200"},
    )
    assert after == before + 1
