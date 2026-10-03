"""Full-text enrichment: the LLM reads the page body, not the feed summary or GDELT slug."""

import trafilatura

from finscrape.models import ScrapedArticle
from finscrape.scrapers import rss
from finscrape.scrapers.world import WorldRSSScraper
from worker.sources import build_enrichers

BODY = "Oil prices jumped after the strait closed. " * 40


def _article(text: str) -> ScrapedArticle:
    return ScrapedArticle(
        url="https://example.com/a", title="Oil jumps", text=text, source="t"
    )


def _fake_page(monkeypatch, body: str) -> None:
    monkeypatch.setattr(rss, "fast_get", lambda url, **_: b"<html/>")
    monkeypatch.setattr(trafilatura, "extract", lambda html, **_: body)
    monkeypatch.setattr(WorldRSSScraper, "fetch_page", lambda self, url, **_: None)


def test_long_summary_still_gets_the_body(monkeypatch):
    _fake_page(monkeypatch, BODY)
    out = WorldRSSScraper().enrich(_article("A summary of moderate length. " * 15))
    assert out.text == BODY


def test_longer_summary_is_kept(monkeypatch):
    summary = "Detailed feed summary. " * 100
    _fake_page(monkeypatch, "short body")
    assert WorldRSSScraper().enrich(_article(summary)).text == summary


def test_text_is_capped(monkeypatch):
    _fake_page(monkeypatch, "x" * 50_000)
    assert len(WorldRSSScraper().enrich(_article("")).text) == rss.MAX_TEXT_CHARS


def test_gdelt_is_enriched():
    assert "gdelt" in build_enrichers()
