"""
Data models for FinScrape events and signals.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Verdict(str, Enum):
    INVEST = "INVEST"
    OBSERVE = "OBSERVE"
    CAUTIOUS = "CAUTIOUS"
    PULL_OUT = "PULL_OUT"

    @classmethod
    def from_score(cls, score: int) -> Verdict:
        # Symmetric: a -2 PULL_OUT hit 56% on realized moves, -3 and below 70%.
        if score >= 3:
            return cls.INVEST
        elif score >= 1:
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
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # --- New enriched analysis fields ---
    reasoning: str = ""
    magnitude: str = "medium"  # low / medium / high
    novelty: str = "standard"  # breaking / standard / follow_up / rehash
    actionability: str = "medium"  # low / medium / high
    affected_entities: list = field(default_factory=list)
    second_order_effects: list = field(default_factory=list)
    sector_impact: str = ""
    key_metrics: dict = field(default_factory=dict)

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
    published_at: Optional[str] = None
    age_hours: Optional[float] = None
    raw_tickers: list[str] = field(default_factory=list)

    @property
    def is_fresh(self) -> bool:
        """Article is within the configured max age window (FINSCRAPE_MAX_AGE_HOURS, default 2)."""
        if self.age_hours is None:
            return True  # assume fresh if unknown
        max_age = float(os.getenv("FINSCRAPE_MAX_AGE_HOURS", "2.0"))
        return self.age_hours <= max_age

    @property
    def has_content(self) -> bool:
        return bool(self.title and self.text and len(self.text.strip()) >= 150)
