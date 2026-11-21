"""Reliability gates (plan M2.3): an upstream being down is a degraded panel, not a 500.

Each test here names the failure it prevents:

* a dead host trips its breaker, the half-open state admits exactly *one* probe, and the
  panel answers 200 with an empty tape;
* a hanging upstream stops holding the request after `upstream_timeout_s`, and the same
  budget is handed to yfinance so the thread is not left downloading forever;
* an unchanged body revalidates to 304 with no body, a changed body is a 200;
* running the ingest cycle twice on the same feed state inserts no duplicates;
* a cycle that fails exits non-zero, so the Action fails and the owner is emailed.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finscrape import market_data
from server.circuit import CircuitBreaker, CircuitOpen
from server.routes import market as market_routes
from server.settings import get_settings

# ------------------------------------------------------------------ circuit breaker


def test_the_breaker_opens_after_n_failures_and_says_so():
    breaker = CircuitBreaker("upstream", fail_threshold=3, reset_after_s=30)
    for _ in range(3):
        breaker.record_failure(now=0.0)
    assert not breaker.allow(now=0.0)
    with pytest.raises(CircuitOpen):
        breaker.call(lambda: "unreachable", now=0.0)


def test_half_open_admits_exactly_one_probe():
    breaker = CircuitBreaker("upstream", fail_threshold=2, reset_after_s=30)
    breaker.record_failure(now=0.0)
    breaker.record_failure(now=0.0)
    assert not breaker.allow(now=29.9)
    # The window elapsed: one caller becomes the probe, every other caller keeps failing fast.
    assert breaker.allow(now=30.0)
    assert not breaker.allow(now=30.0), (
        "a second concurrent caller must not probe the dead host"
    )
    assert not breaker.allow(now=31.0)


def test_a_failed_probe_re_arms_and_a_successful_one_closes():
    breaker = CircuitBreaker("upstream", fail_threshold=1, reset_after_s=10)
    breaker.record_failure(now=0.0)
    assert breaker.allow(now=10.0)  # probe admitted
    breaker.record_failure(now=10.0)
    assert not breaker.allow(now=10.0), (
        "a failed probe re-arms the window instead of retrying"
    )
    assert breaker.allow(now=20.0)
    breaker.record_success()
    assert breaker.allow(now=20.0)
    assert breaker.allow(now=0.0), "a success closes it for good"


def test_a_probe_that_raises_still_re_arms():
    breaker = CircuitBreaker("upstream", fail_threshold=1, reset_after_s=10)
    breaker.record_failure(now=0.0)

    def boom() -> None:
        raise RuntimeError("still down")

    with pytest.raises(RuntimeError):
        breaker.call(boom, now=10.0)
    assert not breaker.allow(now=10.0)


# --------------------------------------------------------------- degraded panel, not 500


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("WORLDFIN_UPSTREAM_TIMEOUT_S", "0.2")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(market_routes.router)
    yield TestClient(app)
    get_settings.cache_clear()


def test_a_dead_quote_upstream_returns_an_empty_tape_not_a_500(client, monkeypatch):
    def dead(symbols, timeout=None):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(market_routes, "get_quotes", dead)
    response = client.get("/api/market/quotes")
    assert response.status_code == 200
    assert response.json()["quotes"] == []
    assert response.json()["symbols"], "the panel still knows what it asked for"


def test_a_hanging_quote_upstream_is_bounded_by_the_configured_timeout(monkeypatch):
    """The handler returns on the budget, not on the download.

    Measured on the handler rather than through TestClient: the client's portal waits for
    the abandoned thread before it shuts the loop down, which would time the download
    instead of the response. The socket timeout in `get_quotes` is what bounds the thread.
    """
    monkeypatch.setenv("WORLDFIN_UPSTREAM_TIMEOUT_S", "0.2")
    get_settings.cache_clear()

    def hang(symbols, timeout=None):
        time.sleep(3)
        return []

    monkeypatch.setattr(market_routes, "get_quotes", hang)

    async def body():
        started = time.perf_counter()
        payload = await market_routes.quotes(None)
        return payload, time.perf_counter() - started

    payload, elapsed = asyncio.run(body())
    assert payload["quotes"] == []
    assert elapsed < 1.0, f"the handler waited {elapsed:.1f}s on a hanging upstream"
    get_settings.cache_clear()


def test_the_download_gets_the_same_timeout_budget(monkeypatch):
    """The route's ceiling is also the socket's, or a thread is left downloading forever."""
    seen: dict = {}

    def fake_download(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(market_data.yf, "download", fake_download)
    monkeypatch.setenv("WORLDFIN_UPSTREAM_TIMEOUT_S", "3.5")
    assert market_data._fetch_quotes(["XOM"]) == {}
    assert seen["timeout"] == pytest.approx(3.5)
    # An explicit budget from the caller wins over the environment.
    market_data._fetch_quotes(["XOM"], timeout=1.25)
    assert seen["timeout"] == pytest.approx(1.25)


def test_the_quote_budget_is_bounded_by_settings():
    from pydantic import ValidationError

    from server.settings import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORLDFIN_UPSTREAM_TIMEOUT_S="0")
    assert Settings(_env_file=None).upstream_timeout_s > 0


# ------------------------------------------------------------------------------ ETag


def _etag_app(monkeypatch) -> TestClient:
    monkeypatch.setenv("WORLDFIN_RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setenv("WORLDFIN_ENABLE_ETAG", "true")
    get_settings.cache_clear()
    from server.middleware import configure_hardening

    app = FastAPI()
    configure_hardening(app)
    state = {"payload": {"n": 1}}

    @app.get("/panel")
    async def panel() -> dict:
        return state["payload"]

    client = TestClient(app)
    client.state = state  # type: ignore[attr-defined]
    return client


def test_an_unchanged_panel_revalidates_to_304_with_no_body(monkeypatch):
    client = _etag_app(monkeypatch)
    first = client.get("/panel")
    etag = first.headers["etag"]
    second = client.get("/panel", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b"", "a 304 must not carry the body it did not change"
    assert second.headers["etag"] == etag


def test_a_changed_panel_returns_200_and_a_new_etag(monkeypatch):
    client = _etag_app(monkeypatch)
    etag = client.get("/panel").headers["etag"]
    client.state["payload"] = {"n": 2}  # type: ignore[attr-defined]
    changed = client.get("/panel", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
    assert changed.json() == {"n": 2}
    get_settings.cache_clear()


# ---------------------------------------------------------------- ingest idempotency

_EVENT = {
    "subject": "Reliability gate: the same headline twice",
    "event_type": "earnings",
    "tickers": ["XOM"],
    "impact_direction": "positive",
    "signal_score": 2,
    "confidence": 0.6,
    "verdict": "OBSERVE",
}


def test_ingesting_the_same_feed_state_twice_inserts_nothing_new():
    """`worker.main --once` twice on an unchanged feed: the second pass is a no-op."""
    from server import db
    from server.ingest import ingest_events
    from tests.server import PG_DSN, pg_reachable

    if not pg_reachable():
        pytest.skip("no Postgres for the ingest idempotency test")

    async def body():
        await db.disconnect()
        pool = await db.connect(PG_DSN)
        try:
            await db.run_migrations(pool)
            await pool.execute("TRUNCATE events RESTART IDENTITY CASCADE")
            first = await ingest_events(pool, [dict(_EVENT)])
            count_after_first = await pool.fetchval("SELECT COUNT(*) FROM events")
            second = await ingest_events(pool, [dict(_EVENT)])
            count_after_second = await pool.fetchval("SELECT COUNT(*) FROM events")
        finally:
            await db.disconnect()
        return first, second, count_after_first, count_after_second

    first, second, after_first, after_second = asyncio.run(body())
    assert first["inserted"] == 1
    assert second["inserted"] == 0 and second["merged"] == 1
    assert after_first == after_second == 1


# ------------------------------------------------------------ a failed cycle exits non-zero


def test_a_failed_cycle_exits_non_zero():
    """An ingest that dies must fail the Action, which is what emails the owner."""
    import os
    import subprocess
    import sys

    from tests.server import pg_reachable

    if not pg_reachable():
        pytest.skip("no Postgres for the exit-code test")

    root = Path(__file__).resolve().parents[1]
    # A DSN that refuses instantly: the cycle cannot bootstrap, so it must exit non-zero.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("WORLDFIN_", "FINSCRAPE_"))
    }
    env["WORLDFIN_DATABASE_URL"] = "postgresql://nobody:nobody@127.0.0.1:1/nowhere"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "worker.main", "--once"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode != 0, "a dead database must fail the ingest job"
    assert result.returncode in (1, 2), f"unexpected exit code {result.returncode}"


# ---------------------------------------------------- quote cache: failure + single-flight


@pytest.fixture()
def clean_quote_cache(monkeypatch):
    """Every test here owns the module-level caches; leaking state makes order matter."""
    monkeypatch.setattr(market_data, "_quote_cache", {})
    monkeypatch.setattr(market_data, "_quote_failures", {})
    monkeypatch.setattr(market_routes, "_quotes_lock", asyncio.Lock())
    return monkeypatch


def test_a_failed_download_is_not_retried_inside_the_failure_window(clean_quote_cache):
    """A dead upstream must not cost one timeout per request: the panel is polled."""
    calls: list[int] = []

    def dead(**kwargs):
        calls.append(1)
        raise RuntimeError("upstream down")

    clean_quote_cache.setattr(market_data.yf, "download", dead)
    clean_quote_cache.setenv("FINSCRAPE_QUOTE_FAIL_TTL", "30")

    assert market_data.get_quotes(["XOM"]) == []
    assert market_data.get_quotes(["XOM"]) == []
    assert len(calls) == 1, "the second request re-downloaded from a host known to be down"


def test_the_failure_window_expires_so_recovery_is_visible(clean_quote_cache):
    calls: list[int] = []

    def dead(**kwargs):
        calls.append(1)
        raise RuntimeError("upstream down")

    clean_quote_cache.setattr(market_data.yf, "download", dead)
    clean_quote_cache.setenv("FINSCRAPE_QUOTE_FAIL_TTL", "0")
    market_data.get_quotes(["XOM"])
    market_data.get_quotes(["XOM"])
    assert len(calls) == 2, "a zero-length failure window must retry immediately"


def test_a_request_during_a_refresh_answers_from_the_snapshot(clean_quote_cache):
    """The second concurrent caller gets the last snapshot instead of queueing behind yfinance."""
    started = []

    def slow(symbols, timeout=None):
        started.append(1)
        time.sleep(0.6)
        return [{"symbol": market_routes.DEFAULT_QUOTE_SYMBOLS[0]}]

    clean_quote_cache.setattr(market_routes, "get_quotes", slow)
    # The route defaults to DEFAULT_QUOTE_SYMBOLS, so the snapshot has to be one of them.
    symbol = market_routes.DEFAULT_QUOTE_SYMBOLS[0]
    clean_quote_cache.setattr(
        market_data, "_quote_cache", {symbol: ({"symbol": symbol}, time.monotonic())}
    )

    async def body():
        first = asyncio.create_task(market_routes.quotes(None))
        await asyncio.sleep(0.05)  # let the first call take the lock
        second_started = time.perf_counter()
        second = await market_routes.quotes(None)
        second_ms = (time.perf_counter() - second_started) * 1000
        await first
        return second, second_ms

    second, second_ms = asyncio.run(body())
    assert len(started) == 1, "the second request started its own download"
    assert second_ms < 300, f"the second request waited {second_ms:.0f} ms on the first"
    assert second["quotes"], "it should have served the snapshot, not an empty tape"
