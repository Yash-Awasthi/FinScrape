"""Corroboration, tier reduction, sector aliasing and single-flight caching.

The ingest pipeline merges same-story coverage into one event before storage
(`FinScrapePipeline._find_duplicate`), so a scenario's cluster is almost always
a single member holding several articles. These pin the pieces that had been
counting members instead.
"""

from __future__ import annotations

import threading
import time

from finscrape.analysis.clusters import cluster_meta
from finscrape.analysis.sectors import TAXONOMY, normalize
from finscrape.scenarios import build_scenarios, score_scenario
from server import cache


def _event(**kw):
    base = {
        "id": 1,
        "subject": "strait closure",
        "reasoning": "",
        "verdict": "PULL_OUT",
        "confidence": 0.8,
        "magnitude": "high",
        "actionability": "high",
        "sector_impact": "energy",
        "tickers": ["XOM"],
        "sources": ["world/a"],
        "articles": ["http://a/1"],
        "created_at": "2026-09-22T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _predict(**kw):
    return {"p_positive_move": 0.8, "data_tier": kw.pop("tier", "empirical")}


class TestCorroboration:
    def test_cluster_meta_counts_distinct_articles_not_members(self):
        meta = cluster_meta([_event(articles=["u1", "u2", "u3"], sources=["a", "b"])])
        assert meta["size"] == 1
        assert meta["reports"] == 3

    def test_reports_never_undercount_members(self):
        """An event with no articles recorded still counts as one report."""
        meta = cluster_meta([_event(id=1, articles=[]), _event(id=2, articles=[])])
        assert meta["reports"] == 2

    def test_a_single_well_corroborated_event_survives_min_size(self):
        """Before this, min_size=2 dropped every event and fell back to singletons."""
        cluster = {
            "members": [_event(articles=["u1", "u2"])],
            "reports": 2,
            "top_subject": "strait closure",
            "sources": ["world/a"],
        }
        lone = {
            "members": [_event(id=9, subject="one off", articles=["u9"])],
            "reports": 1,
            "top_subject": "one off",
            "sources": ["world/b"],
        }
        out = build_scenarios([cluster, lone], [], predict_fn=_predict, limit=5)
        assert [s["title"] for s in out] == ["strait closure"]
        assert out[0]["reports"] == 2


class TestDataTier:
    def test_tier_reports_the_weakest_member_not_the_last(self):
        tiers = iter(["empirical", "no-outcomes", "empirical"])

        def predict(**kw):
            return {"p_positive_move": 0.7, "data_tier": next(tiers)}

        cluster = {
            "members": [_event(id=1), _event(id=2), _event(id=3)],
            "top_subject": "t",
        }
        assert score_scenario(cluster, [], predict)["data_tier"] == "no-outcomes"


class TestSectorNormalisation:
    def test_one_taxonomy_across_surfaces(self):
        assert normalize("energy/defense") == ["energy", "industrials"]
        assert normalize("energy;transportation") == ["energy", "industrials"]
        assert normalize("Finance, consumer_staples") == ["financials", "consumer"]

    def test_aliases_land_inside_the_taxonomy(self):
        from finscrape.analysis.sectors import ALIASES

        assert set(ALIASES.values()) <= set(TAXONOMY)

    def test_blank_yields_no_legs(self):
        assert normalize("") == [] and normalize(None) == []


class TestCacheSingleFlight:
    def test_concurrent_misses_produce_once(self):
        cache.clear()
        calls: list[int] = []

        def slow():
            calls.append(1)
            time.sleep(0.2)
            return "value"

        results: list[object] = []
        threads = [
            threading.Thread(
                target=lambda: results.append(cache.get_or_set("k", 60, slow))
            )
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(calls) == 1, "every concurrent miss re-ran the producer"
        assert results == ["value"] * 5

    def test_a_cached_none_is_not_recomputed(self):
        cache.clear()
        calls: list[int] = []

        def produce():
            calls.append(1)

        assert cache.get_or_set("n", 60, produce) is None
        assert cache.get_or_set("n", 60, produce) is None
        assert len(calls) == 1

    def test_peek_reports_missing_for_an_unset_key(self):
        cache.clear()
        assert cache.peek("absent") is cache.MISSING
