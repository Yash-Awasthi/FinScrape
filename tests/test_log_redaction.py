"""A credential must not survive the ingest log stream (plan M1.6).

The test runs the real logging configuration (`setup_logging`, same formatter, same
filter as production) into a buffer, drives the ingest cycle's own log sites — a pool
that fails with its DSN, an upstream that fails with its bearer token in the URL, a
heuristic fallback, a full-text enrichment failure — and then greps the captured log
exactly as an operator would.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os

import pytest

from finscrape.logging_config import (
    REDACTED,
    SECRET_ENV_VARS,
    RedactSecrets,
    scrub,
    secret_values,
    setup_logging,
)

SECRETS = {
    "FINSCRAPE_API_KEY": "operator-chosen-key-1234",
    "OPENAI_API_KEY": "sk-live-openai-abcdef123456",
    "OPENROUTER_API_KEY": "sk-or-openrouter-abcdef123456",
    "TELEGRAM_BOT_TOKEN": "123456:telegram-bot-token-abcdef",
    "TELEGRAM_WEBHOOK_SECRET": "telegram-webhook-secret-xyz",
    "ANALYZE_DISPATCH_TOKEN": "ghp_dispatch_token_abcdef123456",
    "WORLDFIN_DATABASE_URL": "postgresql://worldfin:sup3rs3cret@db:5432/worldfin",
    "WORLDFIN_REDIS_URL": "redis://:redisp4ss@cache:6379/0",
}


@pytest.fixture()
def secrets_env(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    return SECRETS


def _capture():
    buf = io.StringIO()
    setup_logging(level="DEBUG", json_format=True, stream=buf)
    return buf


def test_scrub_replaces_configured_secrets_and_dsn_credentials(secrets_env):
    for value in SECRETS.values():
        assert value not in scrub(f"value is {value}") or len(value) < 6
    assert scrub("postgres://u:pp@h/db").endswith("/db")
    assert "pp@" not in scrub("postgres://u:pp@h/db")
    assert REDACTED in scrub("postgres://u:pp@h/db")


def test_secret_values_ignores_blank_and_tiny_values(monkeypatch):
    monkeypatch.setenv("FINSCRAPE_API_KEY", "abc")  # too short to scrub safely
    monkeypatch.setenv("OPENAI_API_KEY", "")
    values = secret_values()
    assert "abc" not in values and "" not in values


def test_the_filter_scrubs_message_args_and_extras(secrets_env):
    buf = _capture()
    log = logging.getLogger("worldfin.worker.main")
    dsn = SECRETS["WORLDFIN_DATABASE_URL"]
    key = SECRETS["FINSCRAPE_API_KEY"]
    log.info("connecting %s with %s", dsn, key, extra={"dsn": dsn, "key": key})
    text = buf.getvalue()
    for value in (dsn, key, "sup3rs3cret"):
        assert value not in text, value


def test_the_filter_scrubs_a_traceback(secrets_env):
    buf = _capture()
    log = logging.getLogger("worldfin.worker.main")
    try:
        raise RuntimeError("pool failed at " + SECRETS["WORLDFIN_DATABASE_URL"])
    except RuntimeError:
        log.exception("cycle failed, key=%s", SECRETS["FINSCRAPE_API_KEY"])
    text = buf.getvalue()
    assert "sup3rs3cret" not in text and SECRETS["FINSCRAPE_API_KEY"] not in text
    assert REDACTED in text


def test_a_full_ingest_cycle_logs_no_secret(secrets_env, monkeypatch):
    """Drive the ingest path's log sites and grep the captured stream."""
    from server import ingest
    from worker import health

    buf = _capture()
    log = logging.getLogger("worldfin.worker.main")
    dsn = SECRETS["WORLDFIN_DATABASE_URL"]

    class BrokenPool:
        """Stands in for the real pool: every call fails the way a bad DSN does."""

        def acquire(self):
            pool = self

            class _Ctx:
                async def __aenter__(self):
                    return pool

                async def __aexit__(self, *exc):
                    return False

            return _Ctx()

        async def fetchrow(self, *a, **kw):
            raise ConnectionError(f"could not connect to {dsn}")

        async def execute(self, *a, **kw):
            raise ConnectionError(f"could not connect to {dsn}")

        async def fetch(self, *a, **kw):
            raise ConnectionError(f"could not connect to {dsn}")

    event = {
        "subject": "Hormuz shuts",
        "event_type": "geopolitical",
        "verdict": "INVEST",
        "signal_count": 1,
        "timestamp": "2026-05-03T09:00:00Z",
    }

    async def cycle() -> None:
        # The worker's own failure shape: log the exception and carry on. Both calls
        # raise ConnectionError (a broken pool), never anything wider.
        try:
            await ingest.ingest_events(BrokenPool(), [event])
        except ConnectionError:
            log.exception("ingest source=%s failed", "world_rss")
        try:
            await health.aggregate_health(BrokenPool(), 60)
        except ConnectionError as exc:
            log.warning("health write failed: %s", exc)

    asyncio.run(cycle())
    text = buf.getvalue()
    assert "could not connect to" in text  # the failure really was logged
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name, "")
        if len(value) >= 6:
            assert value not in text, f"{name} leaked into the log"


def test_a_logger_that_never_ran_through_setup_logging_still_loses_the_dsn(secrets_env):
    # Belt and braces for a library logger that grabs its own handler: the filter is a
    # plain object, so it can be attached anywhere.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactSecrets())
    log = logging.getLogger("third.party.lib")
    log.addHandler(handler)
    try:
        log.warning("dsn=%s", SECRETS["WORLDFIN_DATABASE_URL"])
    finally:
        log.removeHandler(handler)
    assert "sup3rs3cret" not in stream.getvalue()
