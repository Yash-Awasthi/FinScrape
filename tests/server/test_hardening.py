"""Phase 8 hardening: unit tests + middleware integration (no DB needed).

The middleware tests mount a throwaway FastAPI app and run `configure_hardening` on it
with a couple of trivial routes, so the security/rate-limit/etag/error-envelope
behaviour is exercised end-to-end without a Postgres pool or the real routers.
"""

from __future__ import annotations

import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server import cache
from server.circuit import CircuitBreaker, CircuitOpen
from server.rate_limit import Limiter, client_key
from server.settings import DEFAULT_API_KEY, get_settings
from server.ssrf import (
    SSRFError,
    assert_public_host,
    assert_public_url,
    is_public_ip,
)


def _request(peer: str, xff: str | None = None) -> object:
    """Stand-in for a Starlette request: only `.client.host` and `.headers` are read."""
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host=peer), headers=headers
    )


# --- SSRF guard -------------------------------------------------------------


def test_is_public_ip_rejects_private_and_loopback():
    for bad in (
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.0.1",
        "::1",
        "0.0.0.0",
    ):
        assert is_public_ip(bad) is False, bad
    for good in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
        assert is_public_ip(good) is True, good


def test_assert_public_host_blocks_loopback_literal():
    with pytest.raises(SSRFError):
        assert_public_host("127.0.0.1")
    # a public literal resolves to itself and passes
    assert_public_host("8.8.8.8")


def test_assert_public_url_rejects_bad_scheme_and_private():
    with pytest.raises(SSRFError):
        assert_public_url("file:///etc/passwd")
    with pytest.raises(SSRFError):
        assert_public_url("http://169.254.169.254/latest/meta-data/")  # cloud metadata


# --- rate limiter -----------------------------------------------------------


def test_limiter_blocks_past_threshold_and_returns_retry():
    lim = Limiter(limit_per_min=3, window_s=60.0)
    assert all(lim.hit("ip", now=0.0)[0] for _ in range(3))
    allowed, retry = lim.hit("ip", now=0.0)
    assert allowed is False
    assert retry >= 1


def test_limiter_window_slides():
    lim = Limiter(limit_per_min=2, window_s=10.0)
    assert lim.hit("ip", now=0.0)[0]
    assert lim.hit("ip", now=1.0)[0]
    assert lim.hit("ip", now=2.0)[0] is False
    # first hit ages out after the 10s window → room again
    assert lim.hit("ip", now=11.0)[0] is True


def test_limiter_zero_disables():
    lim = Limiter(limit_per_min=0)
    assert all(lim.hit("ip")[0] for _ in range(100))


def test_limiter_key_map_is_bounded(monkeypatch):
    monkeypatch.setattr("server.rate_limit.MAX_TRACKED_CLIENTS", 5)
    lim = Limiter(limit_per_min=3)
    for n in range(500):
        lim.hit(f"client-{n}", now=0.0)
    assert len(lim._hits) <= 5


def test_client_key_ignores_spoofed_header_from_public_peer():
    # A public peer IS the client, so its own X-Forwarded-For must not select the key.
    # Documentation ranges like 203.0.113.0/24 are `is_private` in ipaddress, so a real
    # globally-routable address stands in here.
    assert client_key(_request("93.184.216.34", xff="1.2.3.4")) == "93.184.216.34"


def test_client_key_reads_rightmost_hop_behind_a_proxy():
    # private peer = our proxy; it appended the true client last
    assert (
        client_key(_request("172.18.0.5", xff="1.2.3.4, 198.51.100.7"))
        == "198.51.100.7"
    )
    # and with no chain at all the peer itself is the identity
    assert client_key(_request("172.18.0.5")) == "172.18.0.5"


def test_client_key_never_trusts_a_non_ip_peer():
    assert (
        client_key(_request("some-host.internal", xff="1.2.3.4"))
        == "some-host.internal"
    )


# --- circuit breaker --------------------------------------------------------


def test_circuit_opens_then_half_opens_then_recovers():
    cb = CircuitBreaker("x", fail_threshold=2, reset_after_s=5.0)

    def boom():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(boom, now=0.0)
    # tripped → fail fast without calling fn
    with pytest.raises(CircuitOpen):
        cb.call(boom, now=1.0)
    # after reset window → half-open probe allowed; a success closes it
    assert cb.call(lambda: "ok", now=10.0) == "ok"
    assert cb.allow(now=11.0) is True


def test_circuit_half_open_admits_one_probe_only():
    cb = CircuitBreaker("y", fail_threshold=1, reset_after_s=5.0)

    def boom():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        cb.call(boom, now=0.0)  # trips
    assert cb.allow(now=10.0) is True  # the probe
    assert cb.allow(now=10.0) is False  # everyone else waits while it is in flight
    cb.record_failure(now=10.0)
    assert cb.allow(now=12.0) is False  # failed probe re-armed the full interval
    assert cb.allow(now=15.0) is True


# --- cache ------------------------------------------------------------------


def test_cache_memoizes_until_ttl_via_call_count():
    cache.clear()
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return calls["n"]

    a = cache.get_or_set("k", cache.SLOW, produce)
    b = cache.get_or_set("k", cache.SLOW, produce)
    assert a == b == 1
    assert calls["n"] == 1  # second call served from cache


def test_cache_bounds_live_entries(monkeypatch):
    cache.clear()
    monkeypatch.setattr("server.cache._MAX_ENTRIES", 3)
    # every entry stays live (SLOW ttl), so eviction cannot rely on expiry alone
    for n in range(50):
        cache.get_or_set(f"k{n}", cache.SLOW, lambda n=n: n)
    assert len(cache._store) <= 3
    cache.clear()


# --- api key ----------------------------------------------------------------


def test_default_api_key_is_detectable(monkeypatch):
    monkeypatch.delenv("FINSCRAPE_API_KEY", raising=False)
    get_settings.cache_clear()
    assert get_settings().uses_default_api_key is True

    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    get_settings.cache_clear()
    assert get_settings().uses_default_api_key is False
    assert get_settings().api_key != DEFAULT_API_KEY


def test_production_refuses_default_key_and_open_cors(monkeypatch):
    monkeypatch.delenv("FINSCRAPE_API_KEY", raising=False)
    monkeypatch.setenv("WORLDFIN_CORS_ORIGINS", "*")
    monkeypatch.setenv("WORLDFIN_ENV", "production")
    get_settings.cache_clear()
    assert len(get_settings().production_problems()) == 2

    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    monkeypatch.setenv("WORLDFIN_CORS_ORIGINS", "https://worldfin.vercel.app")
    get_settings.cache_clear()
    assert get_settings().production_problems() == []

    monkeypatch.setenv("WORLDFIN_ENV", "development")
    monkeypatch.delenv("FINSCRAPE_API_KEY")
    get_settings.cache_clear()
    assert get_settings().production_problems() == []
    get_settings.cache_clear()


def test_require_api_key_accepts_only_the_configured_key(monkeypatch):
    from fastapi import Depends

    from server.auth import require_api_key

    monkeypatch.setenv("FINSCRAPE_API_KEY", "operator-chosen")
    get_settings.cache_clear()

    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(require_api_key)])
    async def guarded() -> dict:
        return {"ok": True}

    client = TestClient(app)
    assert (
        client.get("/guarded", headers={"X-API-Key": "operator-chosen"}).status_code
        == 200
    )
    assert client.get("/guarded", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/guarded").status_code == 401
    # a non-ASCII key must answer 401, not raise out of the digest comparison
    non_ascii = {"X-API-Key": "café".encode("latin-1")}
    assert client.get("/guarded", headers=non_ascii).status_code == 401
    # the Bearer form is the same credential
    assert (
        client.get(
            "/guarded", headers={"Authorization": "Bearer operator-chosen"}
        ).status_code
        == 200
    )


# --- middleware integration -------------------------------------------------


def _app(monkeypatch, **env) -> FastAPI:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    from server.middleware import configure_hardening

    app = FastAPI()
    configure_hardening(app)

    @app.get("/ping")
    async def ping() -> dict:
        return {"pong": True}

    @app.get("/boom")
    async def boom() -> dict:
        raise HTTPException(status_code=418, detail="teapot")

    return app


def test_security_headers_present(monkeypatch):
    client = TestClient(_app(monkeypatch, WORLDFIN_RATE_LIMIT_PER_MIN="0"))
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers


def test_etag_then_304(monkeypatch):
    client = TestClient(_app(monkeypatch, WORLDFIN_RATE_LIMIT_PER_MIN="0"))
    r1 = client.get("/ping")
    etag = r1.headers.get("etag")
    assert etag and etag.startswith('W/"')
    r2 = client.get("/ping", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    # security headers still ride along on the 304
    assert r2.headers["x-content-type-options"] == "nosniff"


def test_etag_list_and_star_return_304(monkeypatch):
    client = TestClient(_app(monkeypatch, WORLDFIN_RATE_LIMIT_PER_MIN="0"))
    etag = client.get("/ping").headers["etag"]
    for header in (f'W/"stale", {etag}', "*", etag.removeprefix("W/")):
        assert client.get("/ping", headers={"If-None-Match": header}).status_code == 304
    assert (
        client.get("/ping", headers={"If-None-Match": 'W/"stale"'}).status_code == 200
    )


def test_rate_limit_returns_429_with_retry_after(monkeypatch):
    client = TestClient(_app(monkeypatch, WORLDFIN_RATE_LIMIT_PER_MIN="3"))
    codes = [client.get("/ping").status_code for _ in range(5)]
    assert codes.count(200) == 3
    assert codes.count(429) == 2
    blocked = client.get("/ping")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.json()["error"]["status"] == 429


def test_error_envelope_shape(monkeypatch):
    client = TestClient(_app(monkeypatch, WORLDFIN_RATE_LIMIT_PER_MIN="0"))
    r = client.get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"status": 418, "message": "teapot"}}


def teardown_module(module):  # restore the cached settings singleton for other tests
    get_settings.cache_clear()


# --- vendored routers: writes carry the same key as /api/events ---------------
def test_vendored_router_writes_require_the_api_key():
    """The finscrape routers are mounted whole. Their signal-ingest POSTs mutate shared
    analyser state, so they must not be a way around the key /api/events enforces."""
    from fastapi import APIRouter

    from server.app import _guard_mutating_routes

    router = APIRouter()

    @router.get("/probe")
    async def _read() -> dict:
        return {"ok": True}

    @router.post("/probe")
    async def _write() -> dict:
        return {"ok": True}

    _guard_mutating_routes(router)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)

    assert c.get("/probe").status_code == 200  # reads stay open
    assert c.post("/probe").status_code == 401
    key = get_settings().api_key
    assert c.post("/probe", headers={"X-API-Key": key}).status_code == 200


# --- pubsub: a dropped Redis connection must not end the subscriber ------------
def test_pubsub_subscriber_reconnects_after_a_failure(monkeypatch):
    """It runs as a detached task, so a single raise would silently strip
    worker-pushed events from every WS client for the rest of the process."""
    import asyncio

    from server import pubsub

    monkeypatch.setattr(pubsub, "RECONNECT_DELAY_S", 0)
    monkeypatch.setattr(
        pubsub, "get_settings", lambda: types.SimpleNamespace(redis_enabled=True)
    )
    attempts = []

    async def flaky(_handler):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("redis went away")
        raise asyncio.CancelledError

    monkeypatch.setattr(pubsub, "_subscribe_once", flaky)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await pubsub.subscribe_forever(lambda _m: None)

    asyncio.run(run())
    assert len(attempts) == 3


# --- LLM configuration must not fail silently --------------------------------
def test_llm_model_unset_flags_the_placeholder_default(monkeypatch):
    """ "auto" is not a model id. Left as-is against an OpenAI-compatible backend every
    call 404s and analyze_event returns its heuristic, which reads like a real answer."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("FINSCRAPE_MODEL", raising=False)
    get_settings.cache_clear()
    assert get_settings().llm_model_unset is True

    monkeypatch.setenv("FINSCRAPE_MODEL", "claude-sonnet-5")
    get_settings.cache_clear()
    assert get_settings().llm_model_unset is False
    get_settings.cache_clear()


def test_no_backend_means_no_model_warning(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("FINSCRAPE_MODEL", raising=False)
    get_settings.cache_clear()
    assert get_settings().llm_model_unset is False
    get_settings.cache_clear()


def test_openai_key_reaches_the_chat_call(monkeypatch):
    """It was hardcoded to the literal "ollama", so any authenticated OpenAI-compatible
    endpoint answered 401 and the caller silently got heuristic output."""
    from server import ai

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key")
    monkeypatch.setenv("FINSCRAPE_MODEL", "some-model")
    get_settings.cache_clear()

    captured = {}

    class Resp:
        def raise_for_status(self): ...
        def json(self):
            return {"choices": [{"message": {"content": '{"summary": "ok"}'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["auth"] = headers["Authorization"]
        captured["model"] = json["model"]
        return Resp()

    monkeypatch.setattr(ai.requests, "post", fake_post)
    ai.analyze_event({"subject": "x", "verdict": "OBSERVE", "tickers": []})
    assert captured["auth"] == "Bearer sk-real-key"
    assert captured["model"] == "some-model"
    get_settings.cache_clear()
