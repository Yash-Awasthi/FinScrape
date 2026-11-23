"""
Tests for the scraper retry/backoff logic in BaseScraper.fetch_page().

Verifies that transient errors trigger retries, non-retryable errors don't,
and that all retries exhausted returns None gracefully.
"""
from unittest.mock import MagicMock, patch

# ── Install the shared fake engine ────────────────────────────────────────
from tests._scraper_mocks import (
    get_fake_fetcher,
    get_fake_response,
    install_fake_engine,
    reset_fetcher,
)

install_fake_engine()
_FakeFetcher = get_fake_fetcher()
_fake_response = get_fake_response()

from finscrape.fetchers import reset_breakers
from finscrape.fetchers.yahoo import YahooScraper

# Global reset at import time
reset_fetcher()
reset_breakers()


class _FakeError(Exception):
    """Custom exception that embeds a status code in the message."""


def _make_scraper():
    return YahooScraper(max_articles=1)


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_retry_on_429_then_succeed(mock_sleep):
    """A 429 on first attempt should retry and succeed on second."""
    good_response = MagicMock()
    _FakeFetcher.get.side_effect = [_FakeError("HTTP 429 Too Many Requests"), good_response]
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is good_response
        assert _FakeFetcher.get.call_count == 2
        assert mock_sleep.call_count == 1, "should sleep once between retries"
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_no_retry_on_non_retryable_error(mock_sleep):
    """A ValueError (not transient) should not retry."""
    _FakeFetcher.get.side_effect = ValueError("invalid URL format")
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is None
        assert _FakeFetcher.get.call_count == 1
        assert mock_sleep.call_count == 0
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 2)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_all_retries_exhausted_returns_none(mock_sleep):
    """When all retries fail with a transient error, return None."""
    _FakeFetcher.get.side_effect = [_FakeError("HTTP 503 Service Unavailable")] * 2
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is None
        assert _FakeFetcher.get.call_count == 2
        assert mock_sleep.call_count == 1  # sleep between attempts, not after last
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_retry_on_timeout_error(mock_sleep):
    """Timeout errors should trigger retry."""
    good_response = MagicMock()
    _FakeFetcher.get.side_effect = [_FakeError("Connection timed out"), good_response]
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is good_response
        assert _FakeFetcher.get.call_count == 2
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_retry_on_connection_reset(mock_sleep):
    """Connection reset errors should trigger retry."""
    good_response = MagicMock()
    _FakeFetcher.get.side_effect = [_FakeError("Connection was reset by peer"), good_response]
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is good_response
        assert _FakeFetcher.get.call_count == 2
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response


@patch("finscrape.fetchers.FETCH_MAX_RETRIES", 3)
@patch("finscrape.fetchers.FETCH_BASE_DELAY", 0.01)
@patch("finscrape.fetchers.FETCH_MAX_DELAY", 0.05)
@patch("time.sleep")
def test_no_retry_on_first_success(mock_sleep):
    """A successful fetch should not trigger any retry."""
    good_response = MagicMock()
    _FakeFetcher.get.return_value = good_response
    try:
        scraper = _make_scraper()
        result = scraper.fetch_page("https://example.com/article")
        assert result is good_response
        assert _FakeFetcher.get.call_count == 1
        assert mock_sleep.call_count == 0
    finally:
        _FakeFetcher.get.reset_mock()
        _FakeFetcher.get.side_effect = None
        _FakeFetcher.get.return_value = _fake_response
