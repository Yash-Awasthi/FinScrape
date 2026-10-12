"""Phase 4: correlation engine — per-detector tests vs the Appendix A formulas (offline)."""

import pytest

from server.correlate import (
    Cluster,
    Market,
    NewsItem,
    Prediction,
    analyze_correlations,
    cluster_news,
    detect_convergence,
    detect_flow_drop,
    detect_flow_price_divergence,
    detect_market,
    detect_prediction_leads_news,
    detect_triangulation,
    detect_velocity_spike,
    jaccard,
    round1,
    tokenize,
)


def _item(
    title, source_type="wire", ts=1000.0, source=None, link=None, lat=None, lon=None
):
    return NewsItem(
        title=title,
        link=link or title,
        source=source or source_type,
        source_type=source_type,
        timestamp=ts,
        lat=lat,
        lon=lon,
    )


def _cluster(members):
    """Build a Cluster directly so detector tests don't depend on clustering."""
    times = [m.timestamp for m in members]
    return Cluster(
        members=members,
        primary=members[0],
        first_seen=min(times),
        last_updated=max(times),
        lat=None,
        lon=None,
        threat=0.0,
    )


# --- primitives ---


def test_round1_half_up():
    assert round1(0.65) == 0.7  # banker's round() would give 0.6
    assert round1(0.85) == 0.9
    assert round1(2.0) == 2.0


def test_tokenize_drops_short_and_stopwords():
    assert tokenize("The OIL tanker, struck!") == {"oil", "tanker", "struck"}


def test_jaccard():
    assert jaccard(set(), set()) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


# --- clustering ---


def test_cluster_groups_similar_and_separates_distinct():
    items = [
        _item("Oil tanker struck in Hormuz strait", ts=3000),
        _item("Tanker struck in Hormuz strait amid tension", ts=2000, source="b"),
        _item("Central bank holds interest rate steady", ts=1000, source="c"),
    ]
    clusters = cluster_news(items)
    sizes = sorted(len(c.members) for c in clusters)
    assert sizes == [1, 2]  # the two tanker stories cluster; rate story alone


def test_cluster_primary_lowest_tier():
    items = [
        _item(
            "Hormuz tanker incident reported",
            source_type="mainstream",
            ts=2000,
            source="m",
        ),
        _item(
            "Hormuz tanker incident reported now",
            source_type="wire",
            ts=1000,
            source="w",
        ),
    ]
    c = cluster_news(items)[0]
    assert c.primary.source_type == "wire"  # wire outranks mainstream


# --- detectors ---


def test_convergence_needs_three_types_within_window():
    base = 5000.0
    members = [
        _item("X", "wire", base),
        _item("X", "gov", base - 100, source="g"),
        _item("X", "intel", base - 200, source="i"),
    ]
    sig = detect_convergence(_cluster(members))
    assert sig and sig.confidence == pytest.approx(0.9)  # 0.6 + 0.1*3
    assert detect_convergence(_cluster(members[:2])) is None  # only two types


def test_triangulation_requires_wire_gov_intel():
    members = [
        _item("a", "wire"),
        _item("a", "gov", source="g"),
        _item("a", "intel", source="i"),
    ]
    sig = detect_triangulation(_cluster(members))
    assert sig and sig.confidence == 0.9
    assert detect_triangulation(_cluster([_item("a", "wire")])) is None


def test_flow_drop():
    members = [
        _item("Gas pipeline supply halt disrupts exports", "wire"),
        _item("Pipeline output cut", "gov", source="g"),
    ]
    sig = detect_flow_drop(_cluster(members))
    assert sig and sig.confidence == pytest.approx(min(0.9, 0.4 + 2 / 10))


def test_market_explained_vs_silent_vs_none():
    explained = detect_market(Market("XOM", 4.0), topic_mentions=0, entity_news=[1])
    assert explained.type == "explained_market_move"
    assert explained.confidence == pytest.approx(0.8)  # 0.5 + 0.1*1 + 4/20
    silent = detect_market(Market("XOM", 4.0), topic_mentions=0, entity_news=[])
    assert silent.type == "silent_divergence" and silent.confidence == pytest.approx(
        0.8
    )
    assert detect_market(Market("XOM", 4.0), topic_mentions=5, entity_news=[]) is None
    assert (
        detect_market(Market("XOM", 1.0), topic_mentions=0, entity_news=[]) is None
    )  # below 2


def test_flow_price_divergence():
    sig = detect_flow_price_divergence(
        Market("CL=F", 2.0), mentions=0, pipeline_signal_count=0
    )
    assert sig and sig.confidence == pytest.approx(0.65)  # 0.4 + 2/8
    assert (
        detect_flow_price_divergence(Market("CL=F", 2.0), 0, 1) is None
    )  # pipeline signal exists
    assert detect_flow_price_divergence(Market("CL=F", 1.0), 0, 0) is None  # below 1.5


def test_velocity_spike():
    assert detect_velocity_spike(
        "energy", velocity=9, baseline=1
    ).confidence == pytest.approx(0.9)
    assert detect_velocity_spike("energy", velocity=5, baseline=1) is None  # not > 6
    assert detect_velocity_spike("energy", velocity=9, baseline=5) is None  # not > 3x


def test_prediction_leads_news():
    sig = detect_prediction_leads_news(Prediction("CL=F", 10.0), related_activity=0)
    assert sig and sig.confidence == pytest.approx(0.9)
    assert (
        detect_prediction_leads_news(Prediction("CL=F", 10.0), related_activity=5)
        is None
    )


# --- orchestrator ---


def test_first_call_emits_nothing():
    items = [_item("Gas pipeline supply halt", "wire")]
    sigs, snap = analyze_correlations(items, prev_snapshot=None)
    assert sigs == [] and "topics" in snap


def test_second_call_emits_and_floors():
    base = 9000.0
    items = [
        _item("Oil pipeline supply halt in strait", "wire", base, source="w"),
        _item("Oil pipeline supply halt in strait", "gov", base - 10, source="g"),
        _item("Oil pipeline supply halt in strait", "intel", base - 20, source="i"),
    ]
    sigs, _ = analyze_correlations(items, prev_snapshot={"topics": {}})
    types = {s.type for s in sigs}
    # corroboration across wire+gov+intel within window -> convergence + triangulation
    assert "triangulation" in types and "convergence" in types
    assert all(s.confidence >= 0.6 for s in sigs)


def test_dedupe_via_seen_set():
    items = [
        _item("a", "wire"),
        _item("a", "gov", source="g"),
        _item("a", "intel", source="i"),
    ]
    seen: set[str] = set()
    analyze_correlations(items, prev_snapshot={"topics": {}}, seen=seen)
    # second run with the same seen set suppresses the already-emitted signals
    sigs2, _ = analyze_correlations(items, prev_snapshot={"topics": {}}, seen=seen)
    assert sigs2 == []


def test_flow_price_divergence_fires_on_a_drop():
    """A crash with no matching coverage is the divergence the detector exists for —
    gating on the signed change silently ignored every downward move."""
    sig = detect_flow_price_divergence(
        Market("CL=F", -2.0), mentions=0, pipeline_signal_count=0
    )
    assert sig and sig.type == "flow_price_divergence"
    assert sig.value == -2.0
    assert sig.confidence == pytest.approx(0.65)  # 0.4 + |−2|/8


def test_flow_drop_suppresses_flow_price_divergence_end_to_end():
    """The pipeline_signal_count gate is only real if flow_drop has already run.

    Only the seed title carries an energy keyword, so the topic-mention gate stays
    open (1 < 2) and flow_drop is the one thing that can suppress the divergence.
    """
    base = 9000.0
    items = [
        _item("pipeline supply halt reported", "wire", base, source="w"),
        _item("supply halt reported today", "gov", base - 10, source="g"),
    ]
    sigs, _ = analyze_correlations(
        items, markets=[Market("CL=F", 4.0)], prev_snapshot={"topics": {}}
    )
    types = {s.type for s in sigs}
    assert "flow_drop" in types
    assert "flow_price_divergence" not in types

    # Same market move, no supply story in the news -> the divergence does fire.
    quiet = [_item("Local council approves new bike lane", "mainstream", base)]
    sigs2, _ = analyze_correlations(
        quiet, markets=[Market("CL=F", 4.0)], prev_snapshot={"topics": {}}
    )
    assert "flow_price_divergence" in {s.type for s in sigs2}


# --- symbol → topic bridge (replaces the v1 stub that returned 0 off-energy) ---
def test_topic_mentions_uses_the_entity_index_beyond_energy():
    from server.correlate import _topic_mentions_for_symbol

    topics = {"energy": {"velocity": 5}, "conflict": {"velocity": 3}}
    assert _topic_mentions_for_symbol("LMT", topics) == 3  # defense → conflict
    assert _topic_mentions_for_symbol("FDX", {"shipping": {"velocity": 4}}) == 4
    assert _topic_mentions_for_symbol("AAPL", topics) == 0  # no mapped topic


def test_topic_mentions_takes_the_busiest_topic_not_the_sum():
    """XOM sits in several topics and one headline can feed all of them; summing would
    count it repeatedly and over-suppress the divergence detectors."""
    from server.correlate import _topic_mentions_for_symbol, _topics_by_ticker

    assert {"energy", "conflict"} <= _topics_by_ticker()["XOM"]
    topics = {"energy": {"velocity": 5}, "conflict": {"velocity": 3}}
    assert _topic_mentions_for_symbol("XOM", topics) == 5


def test_energy_futures_keep_their_topic_without_an_entity_entry():
    from server.correlate import _topic_mentions_for_symbol, _topics_by_ticker

    assert "CL=F" not in _topics_by_ticker()  # futures carry no keywords of their own
    assert _topic_mentions_for_symbol("CL=F", {"energy": {"velocity": 7}}) == 7


def test_prediction_leads_news_is_reachable_through_the_orchestrator():
    """`related` was looked up by ticker in a topic-keyed dict, so it was always 0 and
    the detector could never be suppressed — nor was it ever fed a prediction."""
    quiet = [_item("Local council approves new bike lane", "mainstream", 9000.0)]
    sigs, _ = analyze_correlations(
        quiet, predictions=[Prediction("LMT", 10.0)], prev_snapshot={"topics": {}}
    )
    assert "prediction_leads_news" in {s.type for s in sigs}

    # Heavy conflict coverage means the prediction is not leading the story.
    busy = [
        _item("missile strike reported in region", "wire", 9000.0, source="w"),
        _item("military attack escalates overnight", "gov", 8990.0, source="g"),
        _item("troops invasion widens war front", "intel", 8980.0, source="i"),
    ]
    sigs2, _ = analyze_correlations(
        busy, predictions=[Prediction("LMT", 10.0)], prev_snapshot={"topics": {}}
    )
    assert "prediction_leads_news" not in {s.type for s in sigs2}


def test_several_stories_of_one_type_all_surface():
    """A daily run covers many stories; one signal per type dropped all but the first."""
    stories = [
        "Oil pipeline supply halt in strait",
        "Wheat export ban hits grain markets",
        "Chip foundry fire halts semiconductor output",
        "Copper mine strike shuts smelter",
    ]
    items = [
        _item(t, tier, 9000.0 - i, source=f"{tier}{n}", link=f"{n}{tier}")
        for n, t in enumerate(stories)
        for i, tier in enumerate(("wire", "gov", "intel"))
    ]
    sigs, _ = analyze_correlations(items, prev_snapshot={"topics": {}})
    conv = [s for s in sigs if s.type == "convergence"]
    assert len(conv) == 3


def test_a_ticker_the_news_named_is_never_a_silent_move():
    """URA, UEC and NIO read as silent_divergence while stories listed them: tickers
    with no keyword entry were never matched to the events that named them."""
    named = NewsItem(
        title="Uranium miners rally on reactor deal",
        link="u",
        source="w",
        tickers=("URA",),
    )
    sigs, _ = analyze_correlations(
        [named],
        markets=[Market(symbol="URA", change=4.0)],
        prev_snapshot={"topics": {}},
    )
    assert "silent_divergence" not in {s.type for s in sigs}
    assert "explained_market_move" in {s.type for s in sigs}
