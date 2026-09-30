"""Test-only real API/SPA launcher; no inherited secrets or upstream network.

Run via web/playwright.live.config.ts against an EMPTY local *_test database.
Only transports are denied: routes, SQL, migrations, seed and UI remain real.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import chdir
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def clean_environment(environment: dict[str, str]) -> dict[str, str]:
    allowed = {"path", "systemroot", "windir", "comspec", "pathext", "temp", "tmp"}
    return {k: v for k, v in environment.items() if k.lower() in allowed}


def validate_database(dsn: str) -> int:
    parsed = urlsplit(dsn)
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or not parsed.path.endswith("_test")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "live E2E requires an explicit 127.0.0.1 port and *_test database"
        )
    return parsed.port


def isolate_environment(directory: str) -> None:
    sys.path.insert(0, str(ROOT))
    environment = clean_environment(dict(os.environ))
    environment.update(
        {
            "HOME": directory,
            "USERPROFILE": directory,
            "LOCALAPPDATA": directory,
            "XDG_CACHE_HOME": directory,
            "PYTHON_DOTENV_DISABLED": "1",
            "FINSCRAPE_DATA_DIR": directory,
            "FINSCRAPE_LAYA": "0",
            "CI": "1",
            "WORLDFIN_E2E_ENV_DIR": directory,
            "OLLAMA_HOST": "http://127.0.0.1:9",
        }
    )
    os.environ.clear()
    os.environ.update(environment)
    import dotenv

    from server.settings import Settings

    dotenv.load_dotenv = lambda *args, **kwargs: False
    Settings.model_config["env_file"] = None


def block_outbound(database_port: int) -> None:
    # Python's audit hook also covers urllib/httpx/async sockets and DNS resolution.
    # Native libcurl bypasses those hooks, so deny both native curl entry points.
    from curl_cffi import AsyncCurl, Curl, CurlError

    def deny_curl(*args, **kwargs):
        raise CurlError("upstream network disabled by live E2E harness")

    Curl.perform = deny_curl
    AsyncCurl.add_handle = deny_curl

    def audit(event, args):
        if event in {
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.getnameinfo",
        }:
            raise OSError("DNS disabled by live E2E harness")
        if event == "socket.getaddrinfo":
            if args[0] != "127.0.0.1" or int(args[1] or 0) != database_port:
                raise OSError("DNS disabled by live E2E harness")
        elif event in {"socket.connect", "socket.sendto"}:
            address = args[1] if event == "socket.connect" else args[-1]
            if address[:2] != ("127.0.0.1", database_port):
                raise OSError("outbound connection disabled by live E2E harness")
        elif event in {"subprocess.Popen", "os.system"}:
            raise OSError("child processes disabled by live E2E harness")

    sys.addaudithook(audit)


async def seed_empty_database(dsn: str) -> None:
    from server import db
    from server.seed.loader import seed

    pool = await db.connect(dsn)
    try:
        if await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema'))"
        ):
            raise RuntimeError(
                "live E2E refuses a nonempty database; create a fresh one"
            )
        await db.run_migrations(pool)
        await seed(pool)
    finally:
        await db.disconnect()


def main() -> None:
    mode = sys.argv[1]
    dsn = os.environ.get("WORLDFIN_TEST_DATABASE_URL", "")
    port = validate_database(dsn)
    with (
        tempfile.TemporaryDirectory(prefix="worldfin-live-") as directory,
        chdir(directory),
    ):
        isolate_environment(directory)
        if mode == "api":
            os.environ.update(
                {
                    "WORLDFIN_DATABASE_URL": dsn,
                    "WORLDFIN_HOST": "127.0.0.1",
                    "WORLDFIN_PORT": "8012",
                }
            )
            asyncio.run(serve_api(dsn, port))
        elif mode == "web":
            node = shutil.which("node")
            if node is None:
                raise RuntimeError("Node.js is required")
            vite = str(ROOT / "web/node_modules/vite/bin/vite.js")
            config = str(ROOT / "web/vite.live.config.ts")
            subprocess.run(
                [node, vite, "build", "--config", config], cwd=ROOT / "web", check=True
            )
            subprocess.run(
                [
                    node,
                    vite,
                    "preview",
                    "--config",
                    config,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "4184",
                    "--strictPort",
                ],
                cwd=ROOT / "web",
                check=True,
            )
        else:
            raise ValueError("expected api or web")


async def serve_api(dsn: str, port: int) -> None:
    # Windows asyncio constructs a loopback socketpair when creating its loop.
    # Install the guard AFTER that internal setup; seed and server share this loop.
    block_outbound(port)
    await seed_empty_database(dsn)
    import uvicorn

    from server.app import create_app

    await uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=8012, log_level="warning")
    ).serve()


if __name__ == "__main__":
    main()
