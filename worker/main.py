"""Worker entrypoint: `python -m worker.main [--once]`.

Two deployments share one body of work. `--once` runs a single cycle and exits —
that is the live path, a GitHub Action against the production database
(`.github/workflows/ingest.yml`). Without it an AsyncIOScheduler keeps the same
work running on intervals, for compose and self-hosted runs.

Both go through `_bootstrap`, so a change to logging, pool sizing or migrations
cannot reach one path and miss the other. Jobs are staggered + jittered so they
don't all hammer the network at once; max_instances=1 + coalesce so a slow cycle
never stacks.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import start_http_server

from finscrape.logging_config import setup_logging
from server import db
from server.settings import Settings, get_settings
from worker import key_queue
from worker.runner import Worker, prune_old_rows
from worker.social import refresh_social

log = logging.getLogger("worldfin.worker.main")


async def _bootstrap() -> tuple[Worker, Settings]:
    """Logging, pool and migrations — identical for both entrypoints."""
    s = get_settings()
    setup_logging(level=s.log_level, json_format=s.log_json)
    pool = await db.connect(
        s.database_url, min_size=s.db_pool_min, max_size=s.db_pool_max
    )
    await db.run_migrations(pool)
    return Worker(pool, max_articles=s.worker_max_articles), s


async def _score_outcomes(worker: Worker) -> int:
    """Backtest matured verdicts. Market data is flaky and scoring is resumable, so a
    failure is logged and the cycle continues rather than taking the worker down."""
    try:
        wrote = await worker.run_backtest()
        log.info("backtest scored %d outcomes", wrote)
        return wrote
    # Scoring resumes next hour.
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        log.warning("backtest skipped: %s", exc)
        return 0


async def _prune(worker: Worker, days: int) -> None:
    """Retention sweep; logged and skipped on failure like the backtest."""
    try:
        await prune_old_rows(worker.pool, days)
    # The sweep reruns tomorrow.
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        log.warning("retention skipped: %s", exc)


def _schedule(worker: Worker, s: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    for name in worker.sources:
        scheduler.add_job(
            worker.run_source,
            "interval",
            minutes=s.gdelt_interval_minutes
            if name == "gdelt"
            else s.worker_interval_minutes,
            args=[name],
            id=name,
            jitter=60,
            max_instances=1,
            coalesce=True,
        )
    if s.enable_correlation:
        # correlate slightly after sources so it sees the freshest ingest
        scheduler.add_job(
            worker.run_correlations,
            "interval",
            minutes=s.worker_interval_minutes,
            id="correlations",
            jitter=30,
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        refresh_social,
        "interval",
        minutes=s.worker_interval_minutes,
        args=[worker.pool],
        id="social",
        jitter=60,
        max_instances=1,
        coalesce=True,
    )
    # Outcomes mature against a price window, not a scrape window, so this keeps its
    # own hourly cadence instead of riding the ingest interval.
    scheduler.add_job(
        _score_outcomes,
        "interval",
        hours=1,
        args=[worker],
        id="backtest",
        jitter=120,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _prune,
        "interval",
        hours=24,
        args=[worker, s.retention_days],
        id="retention",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


async def main() -> None:
    """Long-running worker: every source on an interval, plus correlate and backtest."""
    worker, s = await _bootstrap()
    if s.metrics_port:
        start_http_server(s.metrics_port)
        log.info("worker metrics on :%d/metrics", s.metrics_port)

    scheduler = _schedule(worker, s)
    scheduler.start()
    log.info(
        "worker started: %d sources every %d min, gdelt every %d min",
        len(worker.sources),
        s.worker_interval_minutes,
        s.gdelt_interval_minutes,
    )
    await worker.run_all_once()  # warm-up so the dashboard fills immediately

    try:
        await asyncio.Event().wait()  # run forever
    finally:
        scheduler.shutdown(wait=False)
        await db.disconnect()


async def run_once() -> None:
    """One cycle (every source + correlate + backtest) then exit — the live deploy."""
    worker, s = await _bootstrap()
    await key_queue.load(worker.pool)
    try:
        await worker.run_all_once()  # all sources once + correlate
    finally:
        await key_queue.save(worker.pool)
    await _score_outcomes(worker)
    await _prune(worker, s.retention_days)
    await db.disconnect()


if __name__ == "__main__":
    import sys

    asyncio.run(run_once() if "--once" in sys.argv else main())
