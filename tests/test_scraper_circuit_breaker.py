"""
Tests for the circuit breaker integration in BaseScraper.fetch_page().

Verifies:
  - After N consecutive failures, the breaker trips and fast-fails
  - A successful fetch resets the breaker
  - The breaker is per-source (each scraper name gets its own breaker)
  - reset_breakers() clears all state
"""
from unittest.mock import MagicMock, patch

# ── Install the shared fake engine ────────────────────────────────────────
from tests._scraper_mocks import (
    get_fake_fetcher,
    get_fake_response,
    install_fake_engine,
)

install_fake_engine()
_FakeFetcher = get_fake_fetcher()
_fake_response = get_fake_response()

from finscrape.fetchers import get_breaker, reset_breakers
from finscrape.fetchers.yahoo import YahooScraper


class _FakeError(Exception):
    pass


def _make_scraper():
    return YahooScraper(max_articles=1)


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 1)  # no retries — fast fail
@patch("finscrape.fetchers.CB_FAIL_THRESHOLD", 3)
@patch("finscrape.fetchers.CB_RESET_AFTER_S", 60.0)
@patch("time.sleep")
def test_breaker_trips_after_consecutive_failures(mock_sleep):
    """After CB_FAIL_THRESHOLD consecutive failures, breaker should be open."""
    reset_breakers()
    scraper = _make_scraper()
    _FakeFetcher.get.side_effect = None  # clear any stale side_effect
    _FakeFetcher.get.side_effect = _FakeError("HTTP 503 Service Unavailable")

    # First 3 calls: each fails and records a failure
    for i in range(3):
        result = scraper.fetch_page("https://example.com/article")
        assert result is None, f"call {i+1} should return None"

    breaker = get_breaker("yahoo")
    assert not breaker.allow(), "breaker should be open (tripped) after 3 failures"
    _FakeFetcher.get.reset_mock(side_effect=True)
    _FakeFetcher.get.return_value = _fake_response
    reset_breakers()


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("finscrape.fetchers.CB_FAIL_THRESHOLD", 3)
@patch("time.sleep")
def test_breaker_resets_on_success(mock_sleep):
    """A successful fetch resets the breaker to closed."""
    reset_breakers()
    scraper = _make_scraper()

    # Two failures (below threshold)
    _FakeFetcher.get.side_effect = _FakeError("HTTP 503")
    scraper.fetch_page("https://example.com/a")
    scraper.fetch_page("https://example.com/b")

    breaker = get_breaker("yahoo")
    assert breaker.allow(), "breaker should still be closed (below threshold)"

    # Now a success
    _FakeFetcher.get.side_effect = None
    _FakeFetcher.get.return_value = MagicMock()
    result = scraper.fetch_page("https://example.com/c")
    assert result is not None
    assert breaker.allow(), "breaker should still be closed after success"

    _FakeFetcher.get.reset_mock(side_effect=True)
    reset_breakers()


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 1)
@patch("finscrape.fetchers.CB_FAIL_THRESHOLD", 3)
@patch("time.sleep")
def test_breaker_fast_fails_when_open(mock_sleep):
    """When the breaker is open, fetch_page returns None without hitting the network."""
    reset_breakers()
    scraper = _make_scraper()

    # Trip the breaker manually
    breaker = get_breaker("yahoo")
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.allow()

    # Now even a successful Fetcher.get should not be called
    _FakeFetcher.get.reset_mock(side_effect=True)
    _FakeFetcher.get.return_value = MagicMock()
    call_count_before = _FakeFetcher.get.call_count

    result = scraper.fetch_page("https://example.com/article")
    assert result is None, "should fast-fail when circuit is open"
    assert _FakeFetcher.get.call_count == call_count_before, "should not call Fetcher when circuit is open"

    _FakeFetcher.get.reset_mock(side_effect=True)
    _FakeFetcher.get.return_value = _fake_response
    reset_breakers()


def test_breakers_are_per_source():
    """Each scraper name gets its own breaker."""
    reset_breakers()
    b1 = get_breaker("yahoo")
    b2 = get_breaker("bloomberg")
    assert b1 is not b2, "different sources should have different breakers"
    assert b1.name == "yahoo"
    assert b2.name == "bloomberg"
    reset_breakers()


def test_reset_breakers_clears_all():
    """reset_breakers() clears all circuit breakers."""
    b1 = get_breaker("yahoo")
    b1.record_failure()
    reset_breakers()
    b1_after = get_breaker("yahoo")
    assert b1_after is not b1, "after reset, a new breaker is created"
    assert b1_after.allow(), "new breaker should be closed"
