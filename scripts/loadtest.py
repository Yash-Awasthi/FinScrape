"""Load the read paths at a target rate and report what breaks first (plan M2.5).

    python -m scripts.loadtest --base-url http://127.0.0.1:8010 --rps 50 --seconds 10

It measures p50/p95/p99 per endpoint and prints the bottleneck in one line, because a p95
without a named cause is a number nobody acts on. `/api/market/quotes` and `/api/scenarios`
are included on purpose: one talks to yfinance through a threadpool, the other hits the
storyline builder and its cache.

No dependencies beyond httpx (already in the server group) and the standard library.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

ENDPOINTS = ("/api/events?limit=50", "/api/scenarios", "/api/market/quotes")


@dataclass
class Sample:
    path: str
    ms: float
    status: int


@dataclass
class Report:
    samples: list[Sample] = field(default_factory=list)
    elapsed: float = 0.0

    def for_path(self, path: str) -> list[Sample]:
        return [s for s in self.samples if s.path == path]

    def summary(self) -> dict:
        out = {}
        for path in dict.fromkeys(s.path for s in self.samples):
            rows = self.for_path(path)
            latencies = sorted(r.ms for r in rows)
            out[path] = {
                "requests": len(rows),
                "errors": sum(1 for r in rows if r.status >= 500),
                "p50_ms": _pct(latencies, 0.50),
                "p95_ms": _pct(latencies, 0.95),
                "p99_ms": _pct(latencies, 0.99),
                "max_ms": latencies[-1] if latencies else 0.0,
            }
        return out

    def bottleneck(self) -> str:
        summary = self.summary()
        if not summary:
            return "no requests completed"
        worst = max(summary.items(), key=lambda item: item[1]["p95_ms"])
        path, row = worst
        if row["p95_ms"] < 250:
            return f"no bottleneck at this rate: worst p95 is {path} at {row['p95_ms']:.0f} ms"
        return (
            f"{path} is the bottleneck: p95 {row['p95_ms']:.0f} ms, "
            f"max {row['max_ms']:.0f} ms over {row['requests']} requests"
        )


def _pct(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def drive(base_url: str, rps: float, seconds: float, timeout: float) -> Report:
    import httpx

    report = Report()
    interval = 1.0 / rps
    budget = int(rps * seconds)
    latencies: list[float] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:

        async def one(path: str) -> None:
            started = time.perf_counter()
            try:
                response = await client.get(path)
                status = response.status_code
            except Exception as exc:  # noqa: BLE001 - a timeout is a data point, not a crash
                status = 599 if "timeout" in str(exc).lower() else 0
            elapsed_ms = (time.perf_counter() - started) * 1000
            report.samples.append(Sample(path=path, ms=elapsed_ms, status=status))
            latencies.append(elapsed_ms)

        started_all = time.perf_counter()
        tasks = []
        for i in range(budget):
            path = ENDPOINTS[i % len(ENDPOINTS)]
            tasks.append(asyncio.create_task(one(path)))
            # Open-loop pacing: request i is scheduled at i/rps from the start, so a slow
            # endpoint shows up as a growing queue instead of being hidden by back-pressure.
            next_at = started_all + (i + 1) * interval
            sleep_for = next_at - time.perf_counter()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
        await asyncio.gather(*tasks)
        report.elapsed = time.perf_counter() - started_all
    return report


def print_report(report: Report) -> None:
    summary = report.summary()
    total = len(report.samples)
    print(f"{total} requests in {report.elapsed:.1f}s")
    print(
        f"{'endpoint':34} {'n':>5} {'5xx':>4} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}"
    )
    for path, row in summary.items():
        print(
            f"{path:34} {row['requests']:5d} {row['errors']:4d} "
            f"{row['p50_ms']:6.0f}ms {row['p95_ms']:6.0f}ms {row['p99_ms']:6.0f}ms "
            f"{row['max_ms']:6.0f}ms"
        )
    print(f"bottleneck: {report.bottleneck()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--rps", type=float, default=50.0)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", default="", help="write the summary here")
    args = parser.parse_args(argv)

    parsed = urlparse(args.base_url)
    if not parsed.scheme or not parsed.netloc:
        parser.error(f"--base-url must be absolute, got {args.base_url!r}")

    report = asyncio.run(drive(args.base_url, args.rps, args.seconds, args.timeout))
    print_report(report)
    summary = report.summary()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(
                {"rps": args.rps, "seconds": args.seconds, "endpoints": summary},
                handle,
                indent=2,
            )
    errors = sum(row["errors"] for row in summary.values())
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
