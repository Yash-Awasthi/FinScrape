"""Public API contract (Pydantic v2). Drives the OpenAPI docs at /docs.

These are the wire shapes. `EventIn` mirrors finscrape FinEvent (ingest accepts a
FinEvent.to_dict()); `EventOut` adds server-assigned id/geo/created_at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    """Ingest payload — a finscrape FinEvent dict. Extra keys ignored on the way in."""

    model_config = {"extra": "ignore"}

    subject: str
    event_type: str
    verdict: str
    impact_direction: str = "neutral"
    signal_score: int = 0
    confidence: float = 0.0
    heuristic_impact: float = 0.0
    divergence_flag: bool = False
    reasoning: str = ""
    magnitude: str = "medium"
    novelty: str = "standard"
    actionability: str = "medium"
    sector_impact: str = ""
    tickers: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    articles: list[str] = Field(default_factory=list)
    affected_entities: list[Any] = Field(default_factory=list)
    second_order_effects: list[Any] = Field(default_factory=list)
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None  # ISO; UTC-normalized at ingest


class EventOut(EventIn):
    id: int
    lat: float | None = None
    lon: float | None = None
    created_at: datetime


class IngestBatch(BaseModel):
    events: list[EventIn]


class IngestResponse(BaseModel):
    ok: bool = True
    inserted: int
    duplicates: int
    inserted_ids: list[int] = Field(default_factory=list)


class DashboardStats(BaseModel):
    total_events: int
    by_verdict: dict[str, int] = Field(default_factory=dict)
    last_update: datetime | None = None


class DateCount(BaseModel):
    day: str  # YYYY-MM-DD (UTC)
    count: int


class DatesResponse(BaseModel):
    dates: list[DateCount] = Field(default_factory=list)


class SourceHealth(BaseModel):
    source: str
    status: str
    fetched_at: datetime | None = None
    record_count: int = 0


class HealthResponse(BaseModel):
    status: str  # ok | degraded
    db: bool
    llm: bool
    sources: list[SourceHealth] = Field(default_factory=list)
