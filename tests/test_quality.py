"""Offline quality-report tests: no database, a fake pool returns canned rows.

The SQL itself is exercised by the live job; these lock the mapping (None -> 0),
the rate/summary text and the defect tally.
"""

import asyncio
from types import SimpleNamespace

from worker.quality import QualityReport, collect


class FakePool:
    """Returns the canned rows in query order and records every statement."""

    def __init__(self, *rows):
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows[len(self.calls) - 1]


def _report(**over):
    base = {
        "days": 1,
        "events": 42,
        "missing_sector": 2,
        "missing_tickers": 1,
        "no_score": 3,
        "out_of_range": 0,
        "duplicate_urls": 0,
        "duplicate_extra": 0,
    }
    base.update(over)
    return QualityReport(**base)


def test_collect_maps_rows_and_passes_the_window():
    pool = FakePool(
        {
            "events": 42,
            "missing_sector": 2,
            "missing_tickers": 1,
            "no_score": 3,
            "out_of_range": 0,
        },
        {"urls": 2, "extra": 3},
    )
    report = asyncio.run(collect(pool, days=7))

    assert report == _report(days=7, duplicate_urls=2, duplicate_extra=3)
    assert [args for _, args in pool.calls] == [("7",), ("7",)]
    assert "FROM events" in pool.calls[0][0]
    assert "jsonb_array_elements_text(e.articles)" in pool.calls[1][0]


def test_collect_maps_none_counts_to_zero():
    pool = FakePool(
        dict.fromkeys(
            ("events", "missing_sector", "missing_tickers", "no_score", "out_of_range")
        ),
        {"urls": None, "extra": None},
    )
    report = asyncio.run(collect(pool))

    assert report.events == 0
    assert report.missing_sector == 0
    assert report.duplicate_urls == 0
    assert report.duplicate_extra == 0


def test_rate_and_summary_percentages():
    report = _report()
    assert report.rate(report.missing_sector) == 2 / 42
    assert report.summary() == (
        "quality 1d: 42 events; sector missing 2 (4.8%), tickers missing 1 (2.4%), "
        "score 0 on 3 (7.1%), confidence out of range 0, "
        "duplicate stories 0 URLs / 0 extra rows"
    )


def test_empty_window_rates_are_zero():
    report = _report(events=0, missing_sector=0, missing_tickers=0, no_score=0)
    assert report.rate(0) == 0.0
    assert "sector missing 0 (0.0%)" in report.summary()


def test_defects_count_only_out_of_range_and_duplicate_extras():
    assert _report(out_of_range=2, duplicate_urls=9, duplicate_extra=1).defects == 3
    # Missing sector/ticker/score are legitimate and never defects on their own.
    assert _report(missing_sector=42, missing_tickers=42, no_score=42).defects == 0


def test_scheduler_registers_the_quality_job():
    from server.settings import Settings
    from worker import main as worker_main

    async def _noop():
        return None

    worker = SimpleNamespace(sources=[], run_correlations=_noop)

    async def check():
        scheduler = worker_main._schedule(worker, Settings(_env_file=None))
        try:
            scheduler.start()
            ids = {job.id for job in scheduler.get_jobs()}
            job = scheduler.get_job("quality")
            trigger = job.trigger.interval.total_seconds() if job else None
            args = job.args if job else None
        finally:
            scheduler.shutdown(wait=False)
        return ids, trigger, args

    ids, trigger, args = asyncio.run(check())
    assert ids == {"correlations", "backtest", "retention", "quality"}
    assert trigger == 24 * 3600
    assert args == (worker,)
