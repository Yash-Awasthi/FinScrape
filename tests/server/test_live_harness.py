"""Isolation boundaries for the real-API browser harness."""

import os
import subprocess
import sys

import pytest


def test_environment_drops_credentials_and_keeps_runtime_paths():
    from tests.live_e2e import clean_environment

    result = clean_environment(
        {
            "PATH": "tools",
            "SystemRoot": "Windows",
            "OPENAI_API_KEY": "do-not-use",
            "WORLDFIN_DATABASE_URL": "production",
            "VITE_API_URL": "https://remote",
            "AWS_ACCESS_KEY_ID": "do-not-use",
            "HTTP_PROXY": "https://proxy",
        }
    )
    assert result == {"PATH": "tools", "SystemRoot": "Windows"}


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user@remote.example:5432/example_test",
        "postgresql://user@127.0.0.1:5432/production",
        "postgresql://user@127.0.0.1:5432/example_test?host=remote.example",
        "postgresql://user@localhost:5432/example_test",
    ],
)
def test_database_guard_rejects_nonisolated_targets(dsn):
    from tests.live_e2e import validate_database

    with pytest.raises(ValueError):
        validate_database(dsn)


def test_database_guard_accepts_explicit_loopback_test_database():
    from tests.live_e2e import validate_database

    assert (
        validate_database("postgresql://worldfin@127.0.0.1:55440/browser_test") == 55440
    )


def test_transports_cannot_escape_database_allowlist():
    # A subprocess contains the irreversible Python audit hook. Each actual transport
    # must reject the request before resolving or opening any external connection.
    code = """
from tests.live_e2e import block_outbound
import socket
import requests
from curl_cffi import Curl, CurlOpt, CurlError
block_outbound(55440)
for operation in (
    lambda: socket.getaddrinfo("example.com", 443),
    lambda: socket.create_connection(("127.0.0.1", 8010)),
    lambda: requests.get("https://example.com", timeout=1),
):
    try:
        operation()
    except (OSError, requests.RequestException):
        pass
    else:
        raise AssertionError("network escaped")
curl = Curl()
curl.setopt(CurlOpt.URL, b"https://example.com")
try:
    curl.perform()
except CurlError:
    pass
else:
    raise AssertionError("native curl escaped")
finally:
    curl.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_live_seed_refuses_nonempty_database_without_changing_it():
    import asyncio

    from server import db
    from tests.live_e2e import seed_empty_database
    from tests.server import PG_DSN, pg_reachable

    if not pg_reachable():
        pytest.skip("no isolated Postgres at WORLDFIN_TEST_DATABASE_URL")

    async def check():
        pool = await db.connect(PG_DSN)
        await db.run_migrations(pool)
        before = await pool.fetchval("SELECT COUNT(*) FROM events")
        await db.disconnect()
        with pytest.raises(RuntimeError, match="nonempty database"):
            await seed_empty_database(PG_DSN)
        pool = await db.connect(PG_DSN)
        try:
            assert await pool.fetchval("SELECT COUNT(*) FROM events") == before
        finally:
            await db.disconnect()

    asyncio.run(check())


def test_isolation_ignores_dotenv_and_inherited_settings(tmp_path):
    # Fake values are test fixtures, never real credentials. Use a fresh interpreter
    # so pytest's conftest cannot accidentally provide the isolation being tested.
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-sentinel\n", encoding="utf-8")
    code = """
import os, sys
from tests.live_e2e import isolate_environment
os.chdir(sys.argv[1])
isolate_environment(sys.argv[1])
from server.settings import Settings
from finscrape.config import Config
assert Settings().openai_api_key == ""
assert not Settings().has_llm
assert Config.from_env().openai_base_url == ""
assert "OPENAI_API_KEY" not in os.environ
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "OPENAI_API_KEY": "inherited-sentinel"},
    )
    assert result.returncode == 0, result.stderr
