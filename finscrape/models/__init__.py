"""
Data models for FinScrape events and signals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum

from finscrape.settings import env_float


class Verdict(str, Enum):
    INVEST = "INVEST"
    OBSERVE = "OBSERVE"
    CAUTIOUS = "CAUTIOUS"
    PULL_OUT = "PULL_OUT"

    @classmethod
    def from_score(cls, score: int) -> Verdict:
        # Zero is no call, so it observes; only a negative score is cautious.
        if score >= 3:
            return cls.INVEST
        elif score >= 0:
            return cls.OBSERVE
        elif score >= -2:
            return cls.CAUTIOUS
        else:
            return cls.PULL_OUT


class EventType(str, Enum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    PRICE_TARGET_CHANGE = "price_target_change"
    ANALYST_UPGRADE = "analyst_upgrade"
    ANALYST_DOWNGRADE = "analyst_downgrade"
    MERGER_ACQUISITION = "merger_acquisition"
    REGULATORY_DECISION = "regulatory_decision"
    PRODUCT_LAUNCH = "product_launch"
    MANAGEMENT_CHANGE = "management_change"
    MARKET_MOVEMENT = "market_movement"
    INVESTMENT_ACTIVITY = "investment_activity"
    GEOPOLITICAL_EVENT = "geopolitical_event"
    BANKRUPTCY = "bankrupt"
    IPO = "ipo"
    OTHER = "other"


@dataclass
class FinEvent:
    subject: str
    event_type: str
    tickers: list[str]
    impact_direction: str  # positive, negative, mixed, neutral
    signal_score: int  # -5 to +5
    confidence: float  # 0.0 to 1.0
    verdict: str  # Verdict enum value
    heuristic_impact: float = 0.0
    divergence_flag: bool = False
    sources: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # --- New enriched analysis fields ---
    reasoning: str = ""
    magnitude: str = "medium"  # low / medium / high
    novelty: str = "standard"  # breaking / standard / follow_up / rehash
    actionability: str = "medium"  # low / medium / high
    affected_entities: list = field(default_factory=list)
    second_order_effects: list = field(default_factory=list)
    sector_impact: str = ""
    key_metrics: dict = field(default_factory=dict)
    # Which judge produced this row: model / model_repaired / heuristic / laya. "unknown"
    # only appears on rows written before the column existed (plan m1.3.1).
    analysis_source: str = "unknown"
    # The model the verdict came from, empty for model-free rows.
    model_name: str = ""
    # The article text the call was made from (event page, plan m4.2.1).
    excerpt: str = ""
    # source -> first UTC timestamp that source carried the story (corroboration).
    source_seen: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FinEvent:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ScrapedArticle:
    """Raw article data from a scraper before AI analysis."""
    url: str
    title: str
    text: str
    source: str
    published_at: str | None = None
    age_hours: float | None = None
    raw_tickers: list[str] = field(default_factory=list)

    @property
    def is_fresh(self) -> bool:
        """Article is within the configured max age window (FINSCRAPE_MAX_AGE_HOURS, default 2)."""
        if self.age_hours is None:
            return True  # assume fresh if unknown
        max_age = env_float("FINSCRAPE_MAX_AGE_HOURS", 2.0)
        return self.age_hours <= max_age

    @property
    def has_content(self) -> bool:
        return bool(self.title and self.text and len(self.text.strip()) >= 150)
