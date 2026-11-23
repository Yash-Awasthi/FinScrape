"""Geopolitical topic tagging, feed sections, and the production analysis budget.

No livestock: "live stock market" in the request meant market data, not farm
animals. These tests pin the correction so the feed mix cannot drift back to
agriculture trade press.
"""

from __future__ import annotations

from finscrape.fetchers.world.feeds import (
    FEEDS,
    SECTION_ORDER,
    section_of,
)
from server.correlate import (
    TOPIC_KEYWORDS,
    NewsItem,
    annotate_topics,
    extract_topics,
    topics_for_text,
)


def test_topics_for_text_is_ordered_and_word_bounded():
    assert topics_for_text(
        "Iran closes the Strait of Hormuz after a missile strike, blocking oil tankers"
    ) == ["energy", "conflict", "shipping"]
    # "war" inside "software" is not a conflict story.
    assert "conflict" not in topics_for_text("Software earnings beat estimates")


def test_annotate_topics_returns_copies_and_uses_reasoning():
    row = {
        "id": 1,
        "subject": "Export halt announced",
        "reasoning": "A shipping carrier halted grain exports after a missile strike.",
    }
    out = annotate_topics([row])
    assert out[0]["topics"] == ["conflict", "shipping"]
    assert "topics" not in row, "annotating must not mutate the DB row in place"


def test_extract_topics_still_aggregates_velocity_and_sources():
    items = [
        NewsItem(title="Oil flows resume through the strait", link="", source="wire_a"),
        NewsItem(title="Tanker freight rates fall", link="", source="wire_b"),
    ]
    topics = extract_topics(items)
    assert topics["energy"]["velocity"] == 1
    assert topics["shipping"]["velocity"] == 2
    assert topics["shipping"]["sources"] == {"wire_a", "wire_b"}


def test_geopolitical_feeds_are_registered():
    keys = {feed.key for feed in FEEDS}
    assert {
        "foreign_policy",
        "the_diplomat",
        "al_monitor",
        "crisis_group",
        "atlantic_council",
        "ecfr",
    } <= keys
    assert not any("livestock" in feed.topics for feed in FEEDS)


def test_livestock_was_not_a_news_topic():
    assert "livestock" not in TOPIC_KEYWORDS


def test_every_feed_has_an_analysis_section():
    assert SECTION_ORDER[0] == "security", "geopolitics must lead the budget"
    assert all(section_of(feed.key) in SECTION_ORDER for feed in FEEDS)
    assert section_of("gcaptain") == "shipping"
    assert section_of("defense_one") == "security"
    assert section_of("crisis_group") == "security"
    assert section_of("fed_press") == "macro"
    assert section_of("not_a_feed") == "general"


def test_collect_round_robins_sections_before_feeds(monkeypatch):
    """With a six-article budget and 40 feeds, registry order used to decide which
    kinds of news were ever analysed. The first slots must cover sections instead."""
    from finscrape.fetchers import rss

    def xml(title: str, link: str) -> bytes:
        return (
            b"<rss><channel><item><title>"
            + title.encode()
            + b"</title><link>"
            + link.encode()
            + b"</link></item></channel></rss>"
        )

    monkeypatch.setattr(
        "finscrape.fetchers.world.feed_urls",
        lambda: {
            "bbc_world": "https://example.org/bbc",
            "defense_one": "https://example.org/defense",
        },
    )
    monkeypatch.setattr(
        rss,
        "fast_get",
        lambda url: (
            xml("Defense headline", "https://example.org/a")
            if url.endswith("defense")
            else xml("World headline", "https://example.org/b")
        ),
    )
    from finscrape.fetchers.world import WorldRSSScraper

    articles = WorldRSSScraper(max_articles=1).collect()
    assert articles[0].title == "Defense headline"
