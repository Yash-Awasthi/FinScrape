"""Phase 3 offline tests: source registry + STALE derivation (no DB, no network).

The live worker cycle (scrape→analyze→ingest→source_health, /api/health freshness)
is the docker verify.
"""

import pytest

from worker.health import derive_status
from worker.sources import build_sources


def test_build_sources_has_world_rss_and_event_ingestors(monkeypatch):
    monkeypatch.setenv("RELIEFWEB_APPNAME", "test-app")
    sources = build_sources(max_articles=5)
    assert "world_rss" in sources
    for name in ("usgs_quakes", "gdelt", "reliefweb"):
        assert name in sources and callable(sources[name])
    assert "coingecko" not in sources  # crypto removed from the event mix
    assert "opensky" not in sources  # data layer, not an event source


def test_derive_status_stale_after_window():
    assert derive_status("OK", age_s=10, stale_after_min=60) == "OK"
    assert derive_status("OK", age_s=3601, stale_after_min=60) == "STALE"
    # non-OK statuses pass through untouched; None age never goes stale
    assert derive_status("WARN", age_s=999999, stale_after_min=60) == "WARN"
    assert derive_status("EMPTY", age_s=10, stale_after_min=60) == "EMPTY"
    assert derive_status("OK", age_s=None, stale_after_min=60) == "OK"


def test_velocity_history_builds_a_baseline_and_decays():
    """detect_velocity_spike needs baseline > 0, so a worker that never records past
    cycles can never emit the signal at all."""
    from worker.runner import Worker

    w = Worker.__new__(Worker)  # skip __init__: no pipeline or network needed
    w._corr_velocity = {}

    w._record_velocity({"topics": {"energy": 2}})
    w._record_velocity({"topics": {"energy": 4, "conflict": 1}})
    # energy went quiet; it still records a 0 so its baseline decays
    w._record_velocity({"topics": {"conflict": 3}})

    assert w._corr_velocity["energy"] == [2, 4, 0]
    # conflict only appeared in cycle 2 — no back-fill, so a brand-new topic cannot
    # spike against a baseline it never had.
    assert w._corr_velocity["conflict"] == [1, 3]


def test_velocity_history_window_is_bounded():
    from server.correlate import VELOCITY_WINDOW_DAYS
    from server.settings import get_settings
    from worker.runner import Worker

    w = Worker.__new__(Worker)
    w._corr_velocity = {}
    interval = max(1, get_settings().worker_interval_minutes)
    window = max(2, int(VELOCITY_WINDOW_DAYS * 24 * 60 / interval))
    for i in range(window + 10):
        w._record_velocity({"topics": {"energy": i}})
    assert len(w._corr_velocity["energy"]) == window
    assert w._corr_velocity["energy"][-1] == window + 9


def _fake_worker():
    from worker.runner import Worker

    w = Worker.__new__(Worker)
    w.sources = {"world_rss": list, "gdelt": list}
    w.pool = None
    return w


def test_scheduler_covers_every_source_plus_correlate_and_backtest():
    """The interval worker and the one-shot Action must do the same work; a source
    or job missing here silently never runs in the long-lived deployment."""
    pytest.importorskip("apscheduler")
    from server.settings import Settings
    from worker.main import _schedule

    worker = _fake_worker()
    scheduler = _schedule(worker, Settings(_env_file=None))
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {
        "world_rss",
        "gdelt",
        "social",
        "correlations",
        "backtest",
        "retention",
    }


def test_backtest_failure_does_not_take_the_worker_down():
    """Market data is flaky and scoring is resumable — a bad fetch must not kill the
    process or abort the rest of the cycle."""
    import asyncio

    from worker.main import _score_outcomes

    worker = _fake_worker()

    async def boom() -> int:
        raise RuntimeError("yfinance timed out")

    worker.run_backtest = boom
    assert asyncio.run(_score_outcomes(worker)) == 0


def test_world_rss_reports_each_feed(monkeypatch):
    """A dead feed must be visible on its own, not folded into one world_rss row."""
    from finscrape.scrapers import rss
    from worker.sources import _WorldRSS

    xml = (
        b"<rss><channel><item><title>Ceasefire talks resume</title>"
        b"<link>https://example.org/a</link></item></channel></rss>"
    )
    monkeypatch.setattr(rss, "fast_get", lambda url: None if "dead" in url else xml)
    monkeypatch.setattr(
        "finscrape.scrapers.world.feed_urls",
        lambda: {
            "bbc_world": "https://ok.example/rss",
            "gone": "https://dead.example/rss",
        },
    )
    produce = _WorldRSS(max_articles=5)
    items = produce()
    assert len(items) == 1
    assert produce.feed_health["bbc_world"] == (1, None)
    count, error = produce.feed_health["gone"]
    assert count == 0 and error


def test_gdelt_runs_on_its_own_interval(monkeypatch):
    """GDELT keeps its own interval so a deployment can slow it independently."""
    pytest.importorskip("apscheduler")
    from datetime import timedelta

    from server.settings import Settings
    from worker.main import _schedule

    monkeypatch.setenv("WORLDFIN_GDELT_INTERVAL_MIN", "45")
    jobs = {
        j.id: j for j in _schedule(_fake_worker(), Settings(_env_file=None)).get_jobs()
    }
    assert jobs["gdelt"].trigger.interval == timedelta(minutes=45)
    assert jobs["world_rss"].trigger.interval == timedelta(minutes=15)

    monkeypatch.delenv("WORLDFIN_GDELT_INTERVAL_MIN")
    jobs = {
        j.id: j for j in _schedule(_fake_worker(), Settings(_env_file=None)).get_jobs()
    }
    assert jobs["gdelt"].trigger.interval == timedelta(minutes=15)


def test_one_dead_feed_does_not_degrade_the_service():
    from server.routes.health import sources_healthy
    from server.schemas import SourceHealth

    def rows(dead: int, total: int = 32) -> list[SourceHealth]:
        feeds = [
            SourceHealth(source=f"world/f{i}", status="WARN" if i < dead else "OK")
            for i in range(total)
        ]
        return [SourceHealth(source="gdelt", status="OK"), *feeds]

    assert sources_healthy(rows(1))
    assert not sources_healthy(rows(16))
    assert not sources_healthy([SourceHealth(source="gdelt", status="WARN")])


def test_events_keep_the_articles_tiered_source_tag():
    """Correlation types read the ':<tier>' suffix; storing the worker's source key
    ('world_rss') made every item 'other', so multi-source signals never fired."""
    from types import SimpleNamespace

    from worker.runner import Worker

    seen: list[str] = []

    class Pipeline:
        def _analyze_article(self, source_name, article):
            seen.append(source_name)

        def ai_failed(self):
            return False

        def merged_into(self):
            return {"subject": "s"}

    w = Worker.__new__(Worker)
    w.enrichers, w.pipeline = {}, Pipeline()
    art = SimpleNamespace(url="https://x/1", source="world/bbc_world:mainstream")
    _, merges, _ = w._analyze_blocking("world_rss", [(art, None)])
    assert seen == ["world/bbc_world:mainstream"]
    assert merges == [("s", "https://x/1", "world/bbc_world:mainstream")]


def test_first_correlation_run_can_emit(monkeypatch):
    """The ingest Action runs `--once`: a fresh process whose first run is its only
    one, so a first-run-seeds gate meant production never stored a signal."""
    import asyncio
    from datetime import UTC, datetime

    from worker import runner

    monkeypatch.setattr(runner, "build_sources", lambda n: {})
    monkeypatch.setattr(runner, "build_enrichers", dict)
    monkeypatch.setattr(runner, "FinScrapePipeline", lambda store: None)
    title = "Oil pipeline supply halt in the strait"
    now = datetime.now(UTC)
    rows = [
        {
            "subject": title,
            "sources": [src],
            "articles": [f"https://{i}"],
            "timestamp": now,
            "lat": None,
            "lon": None,
        }
        for i, src in enumerate(["a:wire", "b:gov", "c:intel"])
    ]
    written: list = []

    class Pool:
        async def fetch(self, *a):
            return rows

        async def execute(self, *a):
            written.append(a[2])

    async def nothing(*a):
        return []

    async def first_run():
        w = runner.Worker(Pool())  # PostgresEvents needs a running loop
        monkeypatch.setattr(w, "_recent_markets", nothing)
        monkeypatch.setattr(w, "_recent_predictions", nothing)
        return await w.run_correlations()

    assert asyncio.run(first_run()) > 0
    assert "convergence" in written
