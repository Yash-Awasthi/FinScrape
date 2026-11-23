"""A new event invalidates the storylines cache within one cycle (plan M3.2).

The clustering pass costs an Ollama embedding per subject, so it is cached for 120 s.
The cache key must therefore describe the exact window the clustering reads: newest id,
row count and the source/ticker text sum. If an ingest adds a row (or merges coverage
into an old one) and the key does not move, the dashboard serves a stale cluster list for
two minutes — which reads as "the product missed the story".
"""

from __future__ import annotations

from server.routes.data import storylines_cache_key


def _head(newest=10, considered=10, coverage=1000):
    return {"newest": newest, "considered": considered, "coverage": coverage}


def test_the_same_window_is_the_same_key():
    assert storylines_cache_key(_head()) == storylines_cache_key(_head())


def test_a_new_event_moves_the_key():
    before = storylines_cache_key(_head(newest=10))
    after = storylines_cache_key(_head(newest=11, considered=10))
    assert before != after


def test_a_coverage_merge_moves_the_key_without_a_new_id():
    before = storylines_cache_key(_head(considered=10, coverage=1000))
    after = storylines_cache_key(_head(considered=10, coverage=1001))
    assert before != after


def test_a_full_window_replaces_an_old_row_and_still_moves_the_key():
    # Newest 200: one row enters, the oldest leaves, so the count is flat but coverage
    # is not — the case a count-only key would miss.
    before = storylines_cache_key(_head(newest=200, considered=200, coverage=5000))
    after = storylines_cache_key(_head(newest=201, considered=200, coverage=5001))
    assert before != after


def test_the_limit_is_not_part_of_the_key():
    # The route slices the stored full list for `limit`; caching per limit would pay for
    # the same clustering once per caller.
    assert "limit" not in storylines_cache_key(_head())
