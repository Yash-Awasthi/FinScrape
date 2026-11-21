"""Measure how long the API takes to answer from a cold process (plan M2.5).

    python -m scripts.warm --base-url https://worldfin.onrender.com --cold-seconds 60
    python -m scripts.warm --spawn            # boot a local server and time it

The deploy runs on a free tier that sleeps, and DEPLOY.md quotes a cold start of 30–50 s.
That number decides whether a keep-warm step is needed, so it has to be measurable on demand
instead of remembered from one afternoon.

`--spawn` starts `uvicorn server.main:app` on a spare port and times it to the first 200:
that is the *process* cost, without the platform's cold-boot overhead, so a regression in
import time shows up here even when the hosted tier is asleep.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

HEALTH = "/api/health"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(base_url: str, budget: float) -> float | None:
    """Seconds until the API answers 200 on the health route, or None on timeout."""
    import httpx

    started = time.perf_counter()
    with httpx.Client(timeout=5.0) as client:
        while time.perf_counter() - started < budget:
            try:
                if client.get(f"{base_url}{HEALTH}").status_code == 200:
                    return time.perf_counter() - started
            except Exception:  # noqa: BLE001 - refused/dropped is "not ready yet"
                pass
            time.sleep(0.5)
    return None


def spawn_and_time(budget: float) -> tuple[float | None, str]:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        # Never a pipe: nobody reads it, and a full pipe buffer would freeze the server we
        # are trying to time. The server's own logs are not the measurement.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        seconds = wait_until_ready(f"http://127.0.0.1:{port}", budget)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
    return seconds, f"http://127.0.0.1:{port}"


def verdict(seconds: float | None, budget: float, quoted: float = 50.0) -> str:
    if seconds is None:
        return f"cold start: no answer within {budget:.0f} s — a keep-warm change is required"
    if seconds > quoted:
        return (
            f"cold start: {seconds:.1f} s, above the {quoted:.0f} s quoted in docs/DEPLOY.md — "
            "add a keep-warm dispatch instead of updating the number"
        )
    return f"cold start: {seconds:.1f} s, within the {quoted:.0f} s quoted in docs/DEPLOY.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="", help="a running API to wake")
    parser.add_argument("--spawn", action="store_true", help="boot a local server and time it")
    parser.add_argument("--budget", type=float, default=120.0, help="seconds to wait")
    parser.add_argument("--quoted", type=float, default=50.0, help="the number DEPLOY.md quotes")
    args = parser.parse_args(argv)

    if args.spawn:
        seconds, url = spawn_and_time(args.budget)
    else:
        if not args.base_url:
            parser.error("--base-url or --spawn is required")
        parsed = urlparse(args.base_url)
        if not parsed.scheme or not parsed.netloc:
            parser.error(f"--base-url must be absolute, got {args.base_url!r}")
        seconds = wait_until_ready(args.base_url.rstrip("/"), args.budget)
        url = args.base_url
    print(verdict(seconds, args.budget, args.quoted))
    print(f"  endpoint: {url}{HEALTH}")
    return 0 if seconds is not None and seconds <= args.quoted else 1


if __name__ == "__main__":
    sys.exit(main())
