"""Correlation & clustering engine — Python port of worldmonitor `analysis-core.ts`.

Independent reimplementation (no worldmonitor source copied).
Detects when one story corroborates across independent source-types inside a window,
and flags news↔market divergence — "before it's news".

Each detector is a pure function so it can be unit-tested against its
formulas. `analyze_correlations` orchestrates: extract topics → run detectors in order
(each gated by a dedup `seen` set) → keep the FIRST signal per type → drop confidence
< 0.6. First call (no prev_snapshot) emits nothing, just returns the snapshot.

JS `Math.round(x*10)/10` rounds half-up; Python's round() is banker's, so we use
`round1 = floor(x*10 + 0.5)/10` to match exactly.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from finscrape.entity_map import keywords_for_ticker, tickers_for_keyword

# --- constants (Appendix A) ---
SIMILARITY_THRESHOLD = 0.5
MARKET_MOVE_THRESHOLD = 2.0
PREDICTION_SHIFT = 5.0
NEWS_VELOCITY = 3
FLOW_PRICE = 1.5
ENERGY_SYMS = ("CL=F", "NG=F")
CLUSTER_CAP = 1000
VELOCITY_WINDOW_DAYS = 7
SPIKE_MULTIPLIER = 3.0
CONVERGENCE_WINDOW_S = 3600  # 1h
CONFIDENCE_FLOOR = 0.6

MARKET_TYPES = ("silent_divergence", "flow_price_divergence", "explained_market_move")

# tier authority order — lower index = more authoritative ("lowest tier" for primary)
TIER_ORDER = ("wire", "gov", "intel", "mainstream", "market", "tech", "other")
_TIER_RANK = {t: i for i, t in enumerate(TIER_ORDER)}
_TIER_WEIGHT = {
    "wire": 1.0,
    "gov": 1.0,
    "intel": 0.9,
    "mainstream": 0.6,
    "market": 0.7,
    "tech": 0.5,
    "other": 0.3,
}

STOP_WORDS = {
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "any",
    "can",
    "had",
    "her",
    "was",
    "one",
    "our",
    "out",
    "day",
    "get",
    "has",
    "him",
    "his",
    "how",
    "now",
    "see",
    "two",
    "who",
    "did",
    "its",
    "let",
    "put",
    "say",
    "she",
    "too",
    "use",
    "with",
    "from",
    "this",
    "that",
    "they",
    "have",
    "will",
    "what",
    "when",
    "your",
    "said",
    "than",
    "into",
    "over",
    "after",
    "amid",
    "says",
    "new",
    "more",
}

# starter topic + flow keyword sets (our own facts, not WM source)
TOPIC_KEYWORDS = {
    "energy": ("oil", "gas", "crude", "lng", "opec", "refinery", "pipeline"),
    "conflict": (
        "war",
        "strike",
        "attack",
        "missile",
        "invasion",
        "military",
        "troops",
    ),
    "sanctions": ("sanction", "sanctions", "embargo", "tariff", "ban"),
    "shipping": ("tanker", "shipping", "strait", "canal", "port", "freight"),
    "elections": ("election", "vote", "ballot", "referendum"),
    "monetary": ("rate", "inflation", "fed", "central bank", "yield"),
}
SUPPRESSED: set[str] = set()
PIPELINE_KEYWORDS = ("pipeline", "gas", "oil", "lng", "refinery", "crude")
FLOW_KEYWORDS = (
    "flow",
    "supply",
    "export",
    "shipment",
    "output",
    "production",
    "cut",
    "halt",
    "disruption",
)


def round1(x: float) -> float:
    """JS half-up rounding to 1 decimal."""
    return math.floor(x * 10 + 0.5) / 10


def tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return {w for w in cleaned.split() if len(w) > 2 and w not in STOP_WORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def contains_topic_keyword(text: str, keyword: str) -> bool:
    return (
        re.search(
            rf"(?<![a-z]){re.escape(keyword.lower())}(?![a-z])", (text or "").lower()
        )
        is not None
    )


def includes_keyword(text: str, keyword: str) -> bool:
    return keyword.lower() in (text or "").lower()


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    source_type: str = "other"
    lat: float | None = None
    lon: float | None = None
    timestamp: float = 0.0  # epoch seconds


@dataclass
class Market:
    symbol: str
    change: float  # percent


@dataclass
class Prediction:
    symbol: str
    shift: float  # predicted % move


@dataclass
class Signal:
    type: str
    id: str
    confidence: float
    value: float | None = None
    payload: dict = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        if self.type in MARKET_TYPES:
            return f"{self.type}:{self.id}"
        return f"{self.type}:{self.id}:{round1(self.value or 0.0)}"


@dataclass
class Cluster:
    members: list[NewsItem]
    primary: NewsItem
    first_seen: float
    last_updated: float
    lat: float | None
    lon: float | None
    threat: float

    @property
    def source_types(self) -> set[str]:
        return {m.source_type for m in self.members}


# --- clustering (Appendix A: clusterNewsCore) ---


def cluster_news(items: Iterable[NewsItem]) -> list[Cluster]:
    """Greedy single-pass Jaccard clustering. Seed-vs-candidate only — never transitive,
    clusters never merge. Output sorted by last_updated desc."""
    items = list(items)
    # bound to CLUSTER_CAP, sort newest-first then source/title/link asc for determinism
    items.sort(key=lambda m: (-m.timestamp, m.source, m.title, m.link))
    items = items[:CLUSTER_CAP]

    toks = [tokenize(m.title) for m in items]

    # inverted index token -> [idx asc]
    index: dict[str, list[int]] = {}
    for idx, tset in enumerate(toks):
        for tok in tset:
            index.setdefault(tok, []).append(idx)

    assigned = [False] * len(items)
    clusters: list[Cluster] = []
    for i in range(len(items)):
        if assigned[i]:
            continue
        assigned[i] = True
        member_idx = [i]
        # candidates: idx > i sharing >=1 token
        candidates = sorted({j for tok in toks[i] for j in index.get(tok, []) if j > i})
        for j in candidates:
            if assigned[j]:
                continue
            if jaccard(toks[i], toks[j]) >= SIMILARITY_THRESHOLD:
                assigned[j] = True
                member_idx.append(j)
        clusters.append(_build_cluster([items[k] for k in member_idx]))

    clusters.sort(key=lambda c: c.last_updated, reverse=True)
    return clusters


def _build_cluster(members: list[NewsItem]) -> Cluster:
    primary = min(
        members, key=lambda m: (_TIER_RANK.get(m.source_type, 99), -m.timestamp)
    )
    times = [m.timestamp for m in members]
    # geo = most frequent (lat,lon) among members that have one
    geo_counts: dict[tuple[float, float], int] = {}
    for m in members:
        if m.lat is not None and m.lon is not None:
            geo_counts[(m.lat, m.lon)] = geo_counts.get((m.lat, m.lon), 0) + 1
    geo = max(geo_counts, key=lambda k: geo_counts[k]) if geo_counts else (None, None)
    threat = sum(_TIER_WEIGHT.get(m.source_type, 0.3) for m in members)
    return Cluster(
        members=members,
        primary=primary,
        first_seen=min(times),
        last_updated=max(times),
        lat=geo[0],
        lon=geo[1],
        threat=round1(threat),
    )


# --- detectors (each pure; return a Signal or None) ---


def detect_convergence(cluster: Cluster) -> Signal | None:
    """≥3 items within 1h of the cluster's latest AND ≥3 distinct source-types (excl other)."""
    recent = [
        m
        for m in cluster.members
        if cluster.last_updated - m.timestamp <= CONVERGENCE_WINDOW_S
    ]
    types = {m.source_type for m in recent if m.source_type != "other"}
    if len(recent) >= 3 and len(types) >= 3:
        conf = min(0.95, 0.6 + 0.1 * len(types))
        return Signal(
            "convergence",
            cluster.primary.link,
            conf,
            payload={"types": sorted(types), "count": len(recent)},
        )
    return None


def detect_triangulation(cluster: Cluster) -> Signal | None:
    """Cluster spans all of {wire, gov, intel} → fixed 0.9."""
    if {"wire", "gov", "intel"} <= cluster.source_types:
        return Signal("triangulation", cluster.primary.link, 0.9)
    return None


def detect_flow_drop(cluster: Cluster) -> Signal | None:
    """Cluster titles mention a pipeline keyword AND a flow keyword."""
    text = " ".join(m.title for m in cluster.members)
    has_pipe = any(includes_keyword(text, k) for k in PIPELINE_KEYWORDS)
    has_flow = any(includes_keyword(text, k) for k in FLOW_KEYWORDS)
    if has_pipe and has_flow:
        source_count = len(cluster.source_types)
        return Signal(
            "flow_drop", cluster.primary.link, min(0.9, 0.4 + source_count / 10)
        )
    return None


def detect_market(
    market: Market, topic_mentions: int, entity_news: list
) -> Signal | None:
    """|change|≥2: if entity news found → explained_market_move; else (mentions<2) →
    silent_divergence (the news *didn't* explain the move)."""
    chg = abs(market.change)
    if chg < MARKET_MOVE_THRESHOLD:
        return None
    if entity_news:
        n = len(entity_news)
        return Signal(
            "explained_market_move",
            market.symbol,
            min(0.9, 0.5 + 0.1 * n + chg / 20),
            value=market.change,
        )
    if topic_mentions < 2:
        return Signal(
            "silent_divergence",
            market.symbol,
            min(0.8, 0.4 + chg / 10),
            value=market.change,
        )
    return None


def detect_flow_price_divergence(
    market: Market, mentions: int, pipeline_signal_count: int
) -> Signal | None:
    """Energy symbol moves ≥1.5 either way with <2 mentions and no flow_drop signal yet."""
    chg = abs(market.change)
    if chg >= FLOW_PRICE and mentions < 2 and pipeline_signal_count == 0:
        return Signal(
            "flow_price_divergence",
            market.symbol,
            min(0.85, 0.4 + chg / 8),
            value=market.change,
        )
    return None


def detect_velocity_spike(
    topic: str, velocity: float, baseline: float
) -> Signal | None:
    """Topic velocity > 6 and > 3× its 7d baseline."""
    if velocity > 6 and baseline > 0 and velocity > SPIKE_MULTIPLIER * baseline:
        mult = velocity / baseline
        return Signal(
            "velocity_spike", topic, min(0.9, 0.45 + mult / 8), value=velocity
        )
    return None


def detect_prediction_leads_news(
    pred: Prediction, related_activity: int
) -> Signal | None:
    """A predicted move ≥5 with little corresponding news (<3) — prediction leads the story."""
    shift = abs(pred.shift)
    if shift >= PREDICTION_SHIFT and related_activity < NEWS_VELOCITY:
        return Signal(
            "prediction_leads_news",
            pred.symbol,
            min(0.9, 0.5 + shift / 20),
            value=shift,
        )
    return None


# --- topic extraction + orchestrator ---


def extract_topics(items: list[NewsItem]) -> dict[str, dict]:
    """topic -> {velocity: mention count, sources: set, score: velocity + #sources}."""
    topics: dict[str, dict] = {}
    for item in items:
        for topic, keywords in TOPIC_KEYWORDS.items():
            if topic in SUPPRESSED:
                continue
            if any(contains_topic_keyword(item.title, k) for k in keywords):
                t = topics.setdefault(topic, {"velocity": 0, "sources": set()})
                t["velocity"] += 1
                t["sources"].add(item.source)
    for t in topics.values():
        t["score"] = t["velocity"] + len(t["sources"])
    return topics


@functools.lru_cache(maxsize=1)
def _topics_by_ticker() -> dict[str, frozenset[str]]:
    """ticker -> the topics it trades on, bridged through the keywords both sides share.

    TOPIC_KEYWORDS and the entity index are independent vocabularies that overlap on
    concrete words ('oil', 'missile', 'freight'), so intersecting them maps a symbol to
    its topics without a second hand-maintained table.
    """
    out: dict[str, set[str]] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            for symbol in tickers_for_keyword(keyword):
                out.setdefault(symbol, set()).add(topic)
    return {symbol: frozenset(names) for symbol, names in out.items()}


def _topic_mentions_for_symbol(symbol: str, topics: dict[str, dict]) -> int:
    """Coverage volume plausibly related to a market symbol, as the busiest single topic
    it belongs to.

    Busiest rather than summed: a symbol can sit in several topics (XOM is energy,
    conflict and sanctions) and one headline can feed all of them, so adding the
    velocities would count that headline repeatedly and over-suppress the divergence
    detectors. Distinct from `find_news_for_market_symbol`, which asks whether a
    *specific* story names the symbol — this asks whether the theme is being covered
    at all, which is what separates a silent move from an unattributed one.
    """
    sym = (symbol or "").upper()
    names = _topics_by_ticker().get(sym)
    if not names:
        # Futures carry no entity-index keywords of their own.
        names = frozenset({"energy"}) if sym in ENERGY_SYMS else frozenset()
    return max((topics.get(n, {}).get("velocity", 0) for n in names), default=0)


def find_news_for_market_symbol(symbol: str, items: list[NewsItem]) -> list[NewsItem]:
    """Entity-aware (Phase 12): news items whose title mentions a sector/region keyword
    mapped to `symbol` via finscrape.entity_map. Non-empty → detect_market emits
    explained_market_move instead of collapsing the move to silent_divergence."""
    keywords = keywords_for_ticker(symbol)
    if not keywords:
        return []
    return [
        it for it in items if any(contains_topic_keyword(it.title, k) for k in keywords)
    ]


def analyze_correlations(
    items: list[NewsItem],
    markets: list[Market] | None = None,
    *,
    predictions: list[Prediction] | None = None,
    prev_snapshot: dict | None = None,
    seen: set[str] | None = None,
    velocity_history: dict[str, list[int]] | None = None,
    find_news: Callable[[str, list[NewsItem]], list] = find_news_for_market_symbol,
) -> tuple[list[Signal], dict]:
    """Returns (signals, snapshot). First call (prev_snapshot is None) emits nothing."""
    markets = markets or []
    predictions = predictions or []
    seen = seen if seen is not None else set()
    velocity_history = velocity_history or {}

    topics = extract_topics(items)
    snapshot = {"topics": {k: v["velocity"] for k, v in topics.items()}}
    if prev_snapshot is None:
        return [], snapshot

    clusters = cluster_news(items)
    candidates: list[Signal] = []

    def consider(sig: Signal | None) -> None:
        if sig is None:
            return
        if sig.dedupe_key in seen:
            return
        seen.add(sig.dedupe_key)
        candidates.append(sig)

    # 1. prediction_leads_news
    for pred in predictions:
        # Topics are keyed by topic name, never by symbol — looking one up by ticker
        # always missed, so every prediction read as zero related activity.
        related = _topic_mentions_for_symbol(pred.symbol, topics)
        consider(detect_prediction_leads_news(pred, related))

    # 2. velocity_spike
    for topic, data in topics.items():
        hist = velocity_history.get(topic, [])
        baseline = sum(hist) / len(hist) if hist else 0.0
        consider(detect_velocity_spike(topic, data["velocity"], baseline))

    # 3. market loop (explained / silent)
    for market in markets:
        mentions = _topic_mentions_for_symbol(market.symbol, topics)
        consider(detect_market(market, mentions, find_news(market.symbol, items)))

    # 4. cluster-based
    for cluster in clusters:
        consider(detect_convergence(cluster))
    for cluster in clusters:
        consider(detect_triangulation(cluster))
    for cluster in clusters:
        consider(detect_flow_drop(cluster))

    # 5. flow_price_divergence (energy syms) — runs last because its gate reads the
    # flow_drop count: a detected supply story already explains the price move.
    pipeline_signals = sum(1 for s in candidates if s.type == "flow_drop")
    by_symbol = {m.symbol: m for m in markets}
    for sym in ENERGY_SYMS:
        m = by_symbol.get(sym)
        if m:
            mentions = _topic_mentions_for_symbol(sym, topics)
            consider(detect_flow_price_divergence(m, mentions, pipeline_signals))

    # keep the FIRST signal per type (insertion order), then drop < floor
    first_per_type: dict[str, Signal] = {}
    for sig in candidates:
        first_per_type.setdefault(sig.type, sig)
    signals = [s for s in first_per_type.values() if s.confidence >= CONFIDENCE_FLOOR]
    return signals, snapshot
