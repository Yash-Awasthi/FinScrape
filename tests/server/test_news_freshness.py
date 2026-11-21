"""Latest-news behaviour: recency ordering and disaster-source caps."""

from __future__ import annotations

from finscrape.ingestors.gdelt import export_urls
from finscrape.ingestors.reliefweb import ReliefWebIngestor
from finscrape.ingestors.usgs import USGSQuakesIngestor
from finscrape.models import ScrapedArticle
from finscrape.scrapers.world import WorldRSSScraper, google_news_mirror


def _quake(mag: float, place: str) -> dict:
    return {
        "properties": {
            "mag": mag,
            "place": place,
            "time": 1_760_000_000_000,
            "url": f"https://example.org/{place}",
        },
        "geometry": {"coordinates": [10.0, 20.0]},
    }


def test_usgs_day_feed_and_small_quake_budget():
    ingestor = USGSQuakesIngestor()
    assert ingestor.base_url.endswith("4.5_day.geojson")
    events = ingestor.parse(
        {"features": [_quake(4.6, f"place-{i}") for i in range(30)]}
    )
    assert len(events) == ingestor.max_records == 8


def test_reliefweb_is_a_minority_source():
    assert ReliefWebIngestor().limit == 8


def test_google_news_mirror_is_site_scoped():
    mirror = google_news_mirror("https://www.foreignpolicy.com/feed/")
    assert "site%3Aforeignpolicy.com" in mirror
    assert mirror.startswith("https://news.google.com/rss/search?")
    assert google_news_mirror("not a url") == ""


def test_collect_puts_the_freshest_stories_first(monkeypatch):
    """A six-slot budget must spend its slots on today's news, not a slow feed's
    oldest entry. Section order still leads with security."""

    def article(age: float, title: str) -> ScrapedArticle:
        return ScrapedArticle(
            url=f"https://example.org/{title}",
            title=title,
            text=title,
            source="world/test:mainstream",
            age_hours=age,
        )

    monkeypatch.setattr(
        "finscrape.scrapers.world.feed_urls",
        lambda: {"defense_one": "https://a", "crisis_group": "https://b"},
    )
    monkeypatch.setattr(
        WorldRSSScraper,
        "_fetch_one",
        lambda self, key, url: (
            [article(10, "old-a"), article(1, "new-a")]
            if key == "defense_one"
            else [article(20, "old-b"), article(2, "new-b")],
            None,
        ),
    )
    titles = [a.title for a in WorldRSSScraper(max_articles=10).collect()]
    assert titles == ["new-a", "new-b", "old-a", "old-b"]


def test_gdelt_walks_back_when_the_listed_export_is_not_ready():
    listing = (
        "75104 abc http://data.gdeltproject.org/gdeltv2/20261123201500.export.CSV.zip\n"
        "129162 def http://data.gdeltproject.org/gdeltv2/20261123201500.mentions.CSV.zip\n"
    )
    urls = export_urls(listing)
    assert urls[0] == (
        "https://data.gdeltproject.org/gdeltv2/20261123201500.export.CSV.zip"
    )
    assert urls[1].endswith("20261123200000.export.CSV.zip")
    assert len(urls) == 8
    assert export_urls("nothing here") == []
