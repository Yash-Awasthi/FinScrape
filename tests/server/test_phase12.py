"""Phase 12 — entity→ticker resolution + market cache + pubsub seam (no DB/LLM)."""

from __future__ import annotations

import asyncio

import finscrape.market_data as md
from finscrape.extract.entity_map import keywords_for_ticker, resolve_tickers
from server import pubsub
from server.correlate import (
    Market,
    NewsItem,
    detect_market,
    find_news_for_market_symbol,
)


# --- entity_map -------------------------------------------------------------
def test_resolve_tickers_geopolitics_and_sectors():
    # geopolitics headline with no company named still resolves sector tickers
    hormuz = resolve_tickers("Iran closes the Strait of Hormuz, oil tankers rerouted")
    assert {"XOM", "CVX"} <= set(hormuz)  # oil majors
    assert "RTX" in hormuz  # defense (Iran/Hormuz)
    assert "TSM" in resolve_tickers("Taiwan chip supply at risk")
    assert resolve_tickers("the cat sat on the mat") == []


def test_resolve_tickers_word_boundary():
    # "oil" matches as a word, not inside "spoil"
    assert resolve_tickers("don't spoil the broth") == []
    assert "XOM" in resolve_tickers("crude oil rallies")


def test_keywords_for_ticker_is_reverse_of_resolve():
    kws = keywords_for_ticker("XOM")
    assert "oil" in kws and "hormuz" in kws
    assert keywords_for_ticker("ZZZZ") == []  # unknown symbol


def test_entity_index_tickers_pass_clean_gate():
    # every mapped ticker must satisfy the pipeline's clean_tickers gate (2-5 upper)
    from finscrape.extract.entity_map import _forward

    for tickers in _forward().values():
        for t in tickers:
            assert 1 < len(t) <= 5 and t.isupper(), t


# --- find_news_for_market_symbol → explained_market_move --------------------
def test_find_news_matches_symbol_keywords():
    items = [
        NewsItem(title="Oil prices spike as Hormuz shut", link="", source="reuters"),
        NewsItem(title="Apple earnings beat", link="", source="cnbc"),
    ]
    hits = find_news_for_market_symbol("XOM", items)
    assert [n.title for n in hits] == ["Oil prices spike as Hormuz shut"]
    assert find_news_for_market_symbol("ZZZZ", items) == []


def test_detect_market_explains_move_when_news_found():
    items = [
        NewsItem(title="Crude oil surges on supply shock", link="", source="reuters")
    ]
    news = find_news_for_market_symbol("XOM", items)
    sig = detect_market(
        Market(symbol="XOM", change=3.5), topic_mentions=0, entity_news=news
    )
    assert sig is not None and sig.type == "explained_market_move"
    # with no related news it would fall back to silent_divergence
    silent = detect_market(Market(symbol="XOM", change=3.5), 0, [])
    assert silent is not None and silent.type == "silent_divergence"


# --- market-data TTL cache --------------------------------------------------
def test_market_data_cache_batches_and_dedupes(monkeypatch):
    calls: list[list[str]] = []

    def fake_fetch(tickers):
        calls.append(list(tickers))
        return {t: {"ticker": t, "price": 1.0, "change_percent": 2.0} for t in tickers}

    monkeypatch.setattr(md, "_fetch", fake_fetch)
    md.clear_market_cache()
    first = md.get_market_data(["AAPL", "MSFT", "AAPL"])  # dupe in same call
    second = md.get_market_data(["AAPL", "MSFT"])  # served from cache
    assert len(first) == 2 and len(second) == 2
    assert calls == [["AAPL", "MSFT"]]  # exactly one batched fetch, no dupes


def test_market_data_cache_expires(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(md, "_fetch", lambda ts: (calls.append(list(ts)) or {}) or {})
    monkeypatch.setattr(md, "_ttl", lambda: 0.0)  # everything immediately stale
    md.clear_market_cache()
    md.get_market_data(["AAPL"])
    md.get_market_data(["AAPL"])
    assert len(calls) == 2  # refetched because TTL=0


# --- pubsub seam ------------------------------------------------------------
def test_publish_is_noop_without_redis():
    # default settings have no redis_url → publish returns False, never raises
    assert asyncio.run(pubsub.publish({"type": "new_events"})) is False
