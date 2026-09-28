"""Phase 2 offline tests: feed registry, ingestor parsers (fixtures), geocode, prompt scope.

Pure/parse-only — no network. The network fetch paths are covered by the docker/live
worker run (Phase 3 verify).
"""

from finscrape.analysis.prompts import ANALYSIS_PROMPT, SYSTEM_PROMPT
from finscrape.ingestors import (
    CoinGeckoIngestor,
    GDELTIngestor,
    OpenSkyIngestor,
    ReliefWebIngestor,
    USGSQuakesIngestor,
)
from finscrape.scrapers.world.feeds import (
    FEEDS,
    VALID_RISK,
    VALID_TIERS,
    feed_urls,
    tier_of,
)
from server.geocode import geocode_event, geocode_text

# --- feed registry ---


def test_feeds_valid_and_unique():
    keys = [f.key for f in FEEDS]
    assert len(keys) == len(set(keys)), "duplicate feed keys"
    for f in FEEDS:
        assert f.tier in VALID_TIERS
        assert f.propaganda_risk in VALID_RISK
        assert f.url.startswith("http")


def test_feed_urls_shape_and_tier_lookup():
    urls = feed_urls()
    assert urls["bbc_world"].startswith("https://")
    assert tier_of("un_news") == "gov"
    assert tier_of("nonexistent") == "other"


# --- USGS ---


def test_usgs_parse_filters_and_geo():
    data = {
        "features": [
            {
                "properties": {
                    "mag": 5.2,
                    "place": "near Tokyo, Japan",
                    "time": 1714700000000,
                    "url": "https://usgs/x",
                },
                "geometry": {"coordinates": [139.7, 35.7, 10]},
            },
            {
                "properties": {"mag": 3.0, "place": "minor"},
                "geometry": {"coordinates": [0, 0, 0]},
            },
            {
                "properties": {"mag": 6.0, "place": "no coords"},
                "geometry": {"coordinates": []},
            },
        ]
    }
    events = USGSQuakesIngestor().parse(data)
    assert len(events) == 1  # M3.0 dropped (below 4.5), no-coords dropped
    ev = events[0]
    assert ev.lat == 35.7 and ev.lon == 139.7
    assert "M5.2" in ev.title and ev.published_at is not None


# --- GDELT ---


def test_gdelt_title_comes_from_the_url_slug():
    from finscrape.ingestors.gdelt import slug_title

    assert (
        slug_title(
            "https://www.rnz.co.nz/news/world/1642590/suspected-plot-to-attack-uk-s-fairford-airbase"
        )
        == "Suspected plot to attack uk s fairford airbase"
    )
    assert (
        slug_title(
            "https://article.wn.com/view/2026/09/28/USIran_talks_continue_on_Hormuz_despite_Trumps_rejection/"
        )
        == "USIran talks continue on Hormuz despite Trumps rejection"
    )
    assert slug_title("https://allafrica.com/stories/202609280693.html") == ""


def test_gdelt_export_parses_conflict_events_with_geo():
    from pathlib import Path

    data = (Path(__file__).parent / "fixtures" / "gdelt_export.CSV.zip").read_bytes()
    events = GDELTIngestor(max_records=10).parse(data)
    assert 3 <= len(events) <= 10
    assert all(e.title and e.url.startswith("http") for e in events)
    assert all(
        e.source.startswith("gdelt/") and e.event_type == "geopolitical_event"
        for e in events
    )
    assert any(e.lat is not None for e in events)
    assert "Hormuz" in " ".join(e.title for e in events)
    assert len({e.url for e in events}) == len(events)


# --- ReliefWeb ---


def test_reliefweb_parse():
    data = {
        "data": [
            {
                "fields": {
                    "name": "Flood in Country X",
                    "country": [{"name": "Country X"}],
                    "date": {"created": "2026-01-01T00:00:00+00:00"},
                },
                "href": "h",
            },
            {"fields": {"name": ""}},
        ]
    }
    events = ReliefWebIngestor().parse(data)
    assert len(events) == 1
    assert "Country X" in events[0].text


# --- CoinGecko ---


def test_coingecko_parse_threshold_and_ticker():
    data = [
        {
            "symbol": "btc",
            "name": "Bitcoin",
            "price_change_percentage_24h": 12.3,
            "current_price": 70000,
        },
        {
            "symbol": "eth",
            "name": "Ethereum",
            "price_change_percentage_24h": 2.0,
            "current_price": 3500,
        },
    ]
    events = CoinGeckoIngestor().parse(data)
    assert len(events) == 1  # ETH +2% below 8% threshold
    assert events[0].tickers == ["BTC"] and events[0].event_type == "market_movement"


# --- OpenSky (data layer, not events) ---


def test_opensky_parse_states_not_events():
    data = {
        "states": [
            ["abc123", "FLIGHT1 ", "Germany", 1, 1, 13.4, 52.5, 10000.0, False, 0],
            ["short"],  # malformed, skipped
        ]
    }
    ing = OpenSkyIngestor()
    assert ing.parse(data) == []  # not an event source
    states = ing.parse_states(data)
    assert len(states) == 1
    assert states[0].callsign == "FLIGHT1" and states[0].lat == 52.5


# --- geocode ---


def test_geocode_explicit_passthrough():
    assert geocode_event("anything", explicit_latlon=(10.0, 20.0)) == (10.0, 20.0)


def test_geocode_from_subject_country():
    lat, lon = geocode_event("Tensions rise in Iran over oil exports")
    assert lat is not None and lon is not None


def test_geocode_entity_fallback_and_longest_match():
    lat, lon = geocode_event(
        "Markets jittery", affected_entities=[{"name": "South Korea exporters"}]
    )
    assert (lat, lon) == geocode_text("south korea")
    assert geocode_event("no place named here") == (None, None)


# --- prompt scope widened ---


def test_prompt_widened_to_world():
    assert "geopolitical" in SYSTEM_PROMPT.lower()
    assert "macro" in SYSTEM_PROMPT.lower()
    assert "geopolitical" in ANALYSIS_PROMPT.lower()


# --- feed registry invariants (offline; liveness is a network check, not a test) ---
def test_feed_registry_invariants():
    from finscrape.scrapers.world.feeds import FEEDS, VALID_RISK, VALID_TIERS

    keys = [f.key for f in FEEDS]
    assert len(keys) == len(set(keys)), "duplicate feed key — the key is the source tag"
    urls = [f.url for f in FEEDS]
    assert len(urls) == len(set(urls)), "same URL registered twice"
    for f in FEEDS:
        assert f.tier in VALID_TIERS, f"{f.key}: bad tier"
        assert f.propaganda_risk in VALID_RISK, f"{f.key}: bad propaganda_risk"
        assert f.url.startswith("https://"), f"{f.key}: not https"
        assert f.name and f.region, f"{f.key}: missing name/region"


def test_every_tier_the_correlation_engine_scores_is_represented():
    """detect_convergence needs >=3 distinct source types in one cluster; a registry
    that only spans two tiers can never produce a convergence signal."""
    from finscrape.scrapers.world.feeds import FEEDS
    from server.correlate import _TIER_WEIGHT

    tiers = {f.tier for f in FEEDS}
    assert len(tiers) >= 3, f"only {tiers} — convergence needs 3+ distinct source types"
    assert tiers <= set(_TIER_WEIGHT), (
        f"unscored tier in registry: {tiers - set(_TIER_WEIGHT)}"
    )
