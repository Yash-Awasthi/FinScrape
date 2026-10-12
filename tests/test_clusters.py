"""Pure tests for finscrape.analysis.clusters — fake similarity, no network.

A5 acceptance: the greedy clustering used by /api/storylines must group the same
story from several sources into one storyline, respect a cosine threshold and a
48h time window, and fall back to shared tickers plus headline words when embeddings
are unavailable, as on the Render API.
"""

from datetime import datetime, timedelta, timezone

from finscrape.analysis import clusters


def _ev(
    id: int,
    subject: str,
    *,
    created_at: str | None = None,
    tickers: list[str] | None = None,
    sources: list[str] | None = None,
    score: float = 1.0,
) -> dict:
    return {
        "id": id,
        "subject": subject,
        "tickers": tickers or [],
        "sources": sources or [],
        "signal_score": score,
        "created_at": created_at,
    }


def _ts(offset_hours: int = 0) -> str:
    base = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(hours=offset_hours)).isoformat()


def _identical(a: str, b: str) -> float:
    return 1.0 if a == b else 0.0


class TestClusterEvents:
    def test_identical_subjects_merge_with_ticker_source_union(self):
        events = [
            _ev(1, "Fed cuts rates", created_at=_ts(-2), tickers=["SPY"], sources=["reuters"], score=2),
            _ev(2, "Fed cuts rates", created_at=_ts(-1), tickers=["QQQ"], sources=["bloomberg"], score=1),
        ]
        out = clusters.cluster_events(events, _identical)
        assert len(out) == 1
        c = out[0]
        assert c["size"] == 2
        assert set(c["member_ids"]) == {1, 2}
        assert set(c["tickers"]) == {"SPY", "QQQ"}
        assert set(c["sources"]) == {"reuters", "bloomberg"}
        assert c["avg_score"] == 1.5
        assert c["first_seen"] == _ts(-2)

    def test_below_threshold_stays_separate(self):
        def sim(a: str, b: str) -> float:
            return 0.5 if a != b else 1.0

        events = [_ev(1, "Oil surges"), _ev(2, "Gold glitters")]
        out = clusters.cluster_events(events, sim)
        assert [c["size"] for c in out] == [1, 1]

    def test_same_phrase_outside_window_is_new_story(self):
        # 60h apart — same subject, high similarity, but beyond the 48h window.
        events = [
            _ev(1, "Tariff shock", created_at=_ts(0)),
            _ev(2, "Tariff shock", created_at=_ts(60)),
        ]
        out = clusters.cluster_events(events, _identical)
        assert len(out) == 2
        assert all(c["size"] == 1 for c in out)

    def test_within_window_by_default(self):
        events = [
            _ev(1, "Tariff shock", created_at=_ts(0)),
            _ev(2, "Tariff shock", created_at=_ts(47)),
        ]
        out = clusters.cluster_events(events, _identical)
        assert len(out) == 1
        assert out[0]["size"] == 2

    def test_none_similarity_degrades_to_singletons(self):
        # Ollama down: embed() returns None → cosine returns None → no merges.
        events = [
            _ev(1, "Fed cuts rates", created_at=_ts(-2)),
            _ev(2, "Fed cuts rates", created_at=_ts(-1)),
            _ev(3, "Oil surges", created_at=_ts(0)),
        ]
        out = clusters.cluster_events(events, lambda a, b: None)
        assert len(out) == 3
        assert {c["member_ids"][0] for c in out} == {1, 2, 3}

    def test_missing_timestamps_never_block_merge(self):
        events = [_ev(1, "Story"), _ev(2, "Story")]  # created_at None on both
        out = clusters.cluster_events(events, _identical)
        assert len(out) == 1
        assert out[0]["size"] == 2

    def test_greedy_join_earliest_seed_only(self):
        # Event joins the *first* qualifying cluster; it never appears twice.
        events = [
            _ev(1, "common", created_at=_ts(-3)),
            _ev(2, "unrelated", created_at=_ts(-2)),
            _ev(3, "common", created_at=_ts(-1)),  # similar to seed 1 (first cluster)
        ]
        out = clusters.cluster_events(events, _identical)
        sizes = sorted(c["size"] for c in out)
        assert sizes == [1, 2]
        big = next(c for c in out if c["size"] == 2)
        assert set(big["member_ids"]) == {1, 3}

    def test_clusters_sorted_by_size_desc(self):
        events = [
            _ev(1, "A", created_at=_ts(-4)),
            _ev(2, "B", created_at=_ts(-3)),
            _ev(3, "A", created_at=_ts(-2)),
            _ev(4, "A", created_at=_ts(-1)),
            _ev(5, "B", created_at=_ts(0)),
        ]
        out = clusters.cluster_events(events, _identical)
        assert [c["size"] for c in out] == [3, 2]

    def test_result_is_deterministic_regardless_of_input_order(self):
        subjects = ["A", "A", "B", "A", "B", "C"]
        fwd = [
            _ev(i, s, created_at=_ts(i)) for i, s in enumerate(subjects)
        ]
        rev = list(reversed(fwd))
        o1 = clusters.cluster_events(fwd, _identical)
        o2 = clusters.cluster_events(rev, _identical)
        assert [(c["size"], sorted(c["member_ids"])) for c in o1] == [
            (c["size"], sorted(c["member_ids"])) for c in o2
        ]

    def test_cluster_meta_top_subject_is_newest(self):
        events = [
            _ev(1, "old phrasing", created_at=_ts(-2)),
            _ev(2, "new phrasing", created_at=_ts(0)),
        ]
        out = clusters.cluster_events(events, lambda a, b: 0.9)
        assert out[0]["top_subject"] == "new phrasing"


class TestBuildStorylines:
    def test_without_embeddings_untickered_stories_stay_apart(self, monkeypatch):
        from finscrape.analysis import embeddings

        monkeypatch.setattr(embeddings, "embed", lambda text: None)
        monkeypatch.setattr(embeddings, "cosine", lambda a, b: None)
        events = [_ev(1, "Fed cuts rates", created_at=_ts(-2)), _ev(2, "Fed cuts rates", created_at=_ts(-1))]
        out = clusters.build_storylines(events)
        assert len(out) == 2
        assert all(c["size"] == 1 for c in out)
        # members are the full event dicts (feed renders them unchanged)
        assert {c["members"][0]["id"] for c in out} == {1, 2}

    def test_without_embeddings_shared_ticker_and_headline_merge(self, monkeypatch):
        """Render has no Ollama, so every scenario was a single event."""
        from finscrape.analysis import embeddings

        monkeypatch.setattr(embeddings, "embed", lambda text: None)
        events = [
            _ev(1, "Houthis strike Riyadh airport, Saudi Arabia vows retaliation", created_at=_ts(-3), tickers=["RTX", "XOM"]),
            _ev(2, "Houthi attack on Riyadh airport grounds Saudi flights", created_at=_ts(-2), tickers=["RTX"]),
            _ev(3, "North Korea fires ballistic missile toward east sea", created_at=_ts(-1), tickers=["RTX"]),
            _ev(4, "Riyadh airport reopens after strike", created_at=_ts(0), tickers=["AAPL"]),
        ]
        sizes = {c["size"]: sorted(m["id"] for m in c["members"]) for c in clusters.build_storylines(events)}
        assert sizes[2] == [1, 2]
        assert len(clusters.build_storylines(events)) == 3

    def test_merges_when_embeddings_available(self, monkeypatch):
        from finscrape.analysis import embeddings

        # acme-ish stories all embed identically; anything else is orthogonal.
        monkeypatch.setattr(
            embeddings,
            "embed",
            lambda text: (1.0, 0.0) if "acme" in text else (0.0, 1.0),
        )
        events = [
            _ev(1, "acme beats earnings", created_at=_ts(-2), sources=["reuters"]),
            _ev(2, "acme corp results out", created_at=_ts(-1), sources=["bloomberg"]),
            _ev(3, "acme guidance raised", created_at=_ts(0), sources=["ft"]),
            _ev(4, "Gold at record high", created_at=_ts(0), sources=["cnbc"]),
        ]
        out = clusters.build_storylines(events)
        assert len(out) == 2
        acme = next(c for c in out if c["size"] == 3)
        assert set(acme["member_ids"]) == {1, 2, 3}
        assert set(acme["sources"]) == {"reuters", "bloomberg", "ft"}
        # members newest-first for the feed's top row
        assert acme["members"][0]["id"] == 3
        other = next(c for c in out if c["size"] == 1)
        assert other["member_ids"] == [4]
