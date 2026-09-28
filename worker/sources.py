"""Source registry for the worker.

Each source is a name -> producer() returning a list of (ScrapedArticle, (lat, lon)).
World RSS has no per-item geo (server.geocode derives it from text); structured
ingestors carry exact coords. Producers do network I/O and are called inside a thread.

World RSS returns every fresh entry un-enriched; the worker drops already-seen URLs,
caps the rest, and only then pays for full-text enrichment (`build_enrichers`).
"""

from __future__ import annotations

from collections.abc import Callable

from finscrape.ingestors import EVENT_INGESTORS
from finscrape.models import ScrapedArticle
from finscrape.scrapers.world import WorldRSSScraper

Item = tuple[ScrapedArticle, tuple[float | None, float | None]]
Producer = Callable[[], list[Item]]


class _WorldRSS:
    """World RSS producer that keeps the last cycle's per-feed outcome."""

    def __init__(self, max_articles: int) -> None:
        self.max_articles = max_articles
        self.feed_health: dict[str, tuple[int, str | None]] = {}

    def __call__(self) -> list[Item]:
        scraper = WorldRSSScraper(max_articles=self.max_articles)
        articles = scraper.collect()
        self.feed_health = scraper.feed_health
        return [(a, (None, None)) for a in articles]


def _ingestor_producer(cls) -> Producer:
    def produce() -> list[Item]:
        ingestor = cls()
        data = ingestor.fetch_raw()
        # fetch() maps a failed request to [], which source health would report as
        # EMPTY; raising lets the worker record WARN with the reason.
        if data is None:
            raise RuntimeError(f"{cls.name} fetch failed")
        return [(e.to_article(), (e.lat, e.lon)) for e in ingestor.parse(data)]

    return produce


def build_enrichers() -> dict[str, Callable[[ScrapedArticle], ScrapedArticle]]:
    """Per-source full-text enrichment, applied only to articles about to be analyzed."""
    return {"world_rss": WorldRSSScraper().enrich}


def build_sources(max_articles: int = 20) -> dict[str, Producer]:
    sources: dict[str, Producer] = {"world_rss": _WorldRSS(max_articles)}
    for cls in EVENT_INGESTORS:
        if getattr(cls, "enabled", lambda: True)():
            sources[cls.name] = _ingestor_producer(cls)
    return sources
