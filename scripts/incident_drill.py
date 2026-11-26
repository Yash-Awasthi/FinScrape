"""Offline drill for the six FinScrape incident playbooks.

Run it with `python -m scripts.incident_drill`. Each case drives the real production
code path in this process: `finscrape.analysis.ai_client`, `finscrape.fetchers.world`,
asyncpg's connect path and an in-process HTTP server. Nothing here contacts Render,
Supabase, GitHub or an LLM, and no credentials or database are needed.

Three incidents cannot be reproduced locally. There the drill simulates only the
observable symptom and does not touch the real platform: a refused connection mapped
to `/ready` 503, a stalled request mapped to a timeout, and a non-204 dispatch response
mapped to the cron Worker's throw.

Prints one `PASS incident=<name>` or `FAIL incident=<name> ...` line per case and exits
non-zero if any case failed.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any

import httpx

INCIDENTS = (
    "model_provider_outage",
    "429_exhaustion",
    "supabase_paused",
    "render_cold_start_storm",
    "cron_dispatch_failure",
    "feed_outage",
)

# The 429 body recorded from TokenHarbor on 23 Nov 2026
# (tests/fixtures/llm_responses.json, tokenharbor_429_request_forbidden).
RECORDED_429 = {
    "error": {
        "message": "request_forbidden: free allowance spent for this key",
        "type": "requests",
    }
}

# Same failure the provider seam raises when the endpoint is unreachable.
REFUSED = "connect: connection refused"


@contextmanager
def patched_env(values: dict[str, str | None]) -> Iterator[None]:
    """Set environment values for one case, then put back exactly what was there."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RecordedReply:
    """A recorded provider reply with the fields the AI client touches."""

    def __init__(self, status: int, body: dict) -> None:
        self.status_code = status
        self.body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self.body


def model_provider_outage() -> None:
    """Every backend refuses at connect: the call degrades to None, never raises."""
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

    from finscrape.analysis import ai_client

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise CurlConnectionError(REFUSED)

    saved_post = ai_client.requests.post
    saved_delay = ai_client.RETRY_BASE_DELAY
    saved_moves = ai_client.key_moves()
    try:
        ai_client.requests.post = refuse
        ai_client.RETRY_BASE_DELAY = 0.0
        ai_client._moved_at.clear()
        with patched_env(
            {
                "FINSCRAPE_WIRE_API": "chat",
                "OPENAI_BASE_URL": "http://llm.invalid/v1",
                "OPENAI_API_KEY": "key-a",
                "OPENAI_API_KEYS": None,
                "OPENROUTER_API_KEY": None,
                "FINSCRAPE_MODEL_FALLBACK": None,
                "FINSCRAPE_DAILY_TOKEN_CEILING": None,
            }
        ):
            ai_client.clear_cache()
            assert ai_client._dispatch("p", "s", "m") is None
            assert ai_client.call_ai("p", "s") is None
    finally:
        ai_client.requests.post = saved_post
        ai_client.RETRY_BASE_DELAY = saved_delay
        ai_client._moved_at.clear()
        ai_client._moved_at.update(saved_moves)
        ai_client.clear_cache()


def exhaustion_429() -> None:
    """Every key answers 429: each fingerprint moves back and the loop returns None."""
    from finscrape.analysis import ai_client

    def throttled(*_args: Any, **_kwargs: Any) -> RecordedReply:
        return RecordedReply(429, RECORDED_429)

    keys = ["key-spent-one", "key-spent-two"]
    saved_post = ai_client.requests.post
    saved_delay = ai_client.RETRY_BASE_DELAY
    saved_moves = ai_client.key_moves()
    try:
        ai_client.requests.post = throttled
        ai_client.RETRY_BASE_DELAY = 0.0
        ai_client._moved_at.clear()
        with patched_env(
            {
                "OPENAI_BASE_URL": "http://llm.invalid/v1",
                "OPENAI_API_KEY": keys[0],
                "OPENAI_API_KEYS": keys[1],
            }
        ):
            assert ai_client._call_openai_proxy("p", "s") is None
            moved = ai_client.key_moves()
            for key in keys:
                assert ai_client.key_fingerprint(key) in moved, key
            assert set(ai_client._proxy_keys()) == set(keys)
    finally:
        ai_client.requests.post = saved_post
        ai_client.RETRY_BASE_DELAY = saved_delay
        ai_client._moved_at.clear()
        ai_client._moved_at.update(saved_moves)


def supabase_paused() -> None:
    """A closed port refuses quickly: the same failure `/ready` turns into 503."""
    import asyncpg

    async def connect_once() -> float:
        started = time.perf_counter()
        try:
            conn = await asyncpg.connect(
                "postgresql://u:p@127.0.0.1:1/db", timeout=2
            )
        except (OSError, TimeoutError):
            return time.perf_counter() - started
        await conn.close()
        raise AssertionError("127.0.0.1:1 must not accept a connect")

    elapsed = asyncio.run(connect_once())
    assert elapsed < 3.0, f"refusal took {elapsed:.2f}s, the 2s timeout should bound it"


class _Always500(http.server.BaseHTTPRequestHandler):
    """The dispatch endpoint answering non-204, exactly what the Worker throws on."""

    def do_POST(self) -> None:
        body = b"dispatch rejected"
        self.send_response(500)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return None


def dispatch_error(status: int, body: str, job: str = "ingest.yml") -> str | None:
    """The Worker's check: `if (res.status !== 204) throw` (ops/ingest-cron/index.mjs)."""
    if status != 204:
        return f"dispatch {job} {status}: {body}"
    return None


def cron_dispatch_failure() -> None:
    """A 500 from the dispatch API is detected as the Worker's throw."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Always500)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        with httpx.Client(timeout=2.0) as client:
            response = client.post(f"http://127.0.0.1:{port}/dispatches")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    error = dispatch_error(response.status_code, response.text)
    assert error is not None and "500" in error, error
    assert dispatch_error(204, "") is None


def render_cold_start_storm() -> None:
    """An endpoint that accepts and never replies: ten GETs all time out, fast."""
    async def scenario() -> tuple[list[str], float]:
        async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            with suppress(Exception):
                while await reader.read(1024):
                    pass
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

        server = await asyncio.start_server(hold, "127.0.0.1", 0)
        assert server.sockets is not None
        port = int(server.sockets[0].getsockname()[1])
        url = f"http://127.0.0.1:{port}/health"

        async def probe(client: httpx.AsyncClient) -> str:
            try:
                await client.get(url)
            except httpx.TimeoutException:
                return "timeout"
            return "answered"

        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                started = time.perf_counter()
                outcomes = await asyncio.gather(*(probe(client) for _ in range(10)))
                elapsed = time.perf_counter() - started
        finally:
            server.close()
            await server.wait_closed()
        return outcomes, elapsed

    outcomes, elapsed = asyncio.run(scenario())
    assert outcomes == ["timeout"] * 10, outcomes
    assert elapsed < 5.0, f"ten 0.5s probes took {elapsed:.2f}s"


def feed_outage() -> None:
    """One feed refuses: `feed_health` records the error the worker stores as WARN."""
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

    from finscrape.fetchers import rss as rss_module
    from finscrape.fetchers import world as world_module
    from finscrape.fetchers.world import WorldRSSScraper

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise CurlConnectionError("feed unreachable")

    # "localhost:1" has no dot, so google_news_mirror() returns "" and no mirror is tried.
    scraper = WorldRSSScraper(max_articles=1)
    scraper.feeds = {"dead": "http://localhost:1/rss"}
    saved_rss = rss_module.fast_get
    saved_world = world_module.fast_get
    try:
        rss_module.fast_get = refuse
        world_module.fast_get = refuse
        articles = scraper.collect()
    finally:
        rss_module.fast_get = saved_rss
        world_module.fast_get = saved_world

    count, error = scraper.feed_health["dead"]
    assert articles == []
    assert count == 0
    assert error and "unreachable" in error, error


CASES: tuple[tuple[str, Callable[[], None]], ...] = (
    ("model_provider_outage", model_provider_outage),
    ("429_exhaustion", exhaustion_429),
    ("supabase_paused", supabase_paused),
    ("render_cold_start_storm", render_cold_start_storm),
    ("cron_dispatch_failure", cron_dispatch_failure),
    ("feed_outage", feed_outage),
)


def main() -> int:
    # The real code paths log their failures; the drill reports them as PASS/FAIL lines.
    logging.disable(logging.CRITICAL)
    failures = 0
    started = time.perf_counter()
    for name, case in CASES:
        try:
            case()
        except Exception as exc:  # noqa: BLE001 - every failure is a FAIL line
            failures += 1
            print(f"FAIL incident={name} {type(exc).__name__}: {exc}")
        else:
            print(f"PASS incident={name}")
    elapsed = time.perf_counter() - started
    print(f"{len(CASES) - failures}/{len(CASES)} passed in {elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
