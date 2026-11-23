"""The demo seed fills every dashboard view, deterministically (plan M3.5).

`make demo` is the first thing a new contributor runs. If a view is empty on that first
run, the product looks broken before any code is read; if two runs differ, a screenshot
cannot be compared. This pins both: the dataset covers each view's data prerequisite,
and resolution is a pure function of the clock it is given.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from server.seed.loader import load_dataset, resolve_events

NOW = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)
DATA = load_dataset()
EVENTS = DATA["events"]


def test_today_has_geolocated_events_of_every_verdict() -> None:
    verdicts = Counter(e["verdict"] for e in EVENTS)
    assert {"INVEST", "PULL_OUT", "CAUTIOUS", "OBSERVE"} <= set(verdicts)
    assert all(e.get("lat") is not None and e.get("lon") is not None for e in EVENTS)
    # The globe draws one column per event, colored by verdict, so a missing class is a
    # missing color, not just a missing row.
    assert verdicts["INVEST"] >= 1 and verdicts["PULL_OUT"] >= 1
    sectors = {e.get("sector_impact", "") for e in EVENTS}
    assert len(sectors) >= 5, sectors


def test_tickers_and_sources_views_have_material() -> None:
    tickers = {t for e in EVENTS for t in e.get("tickers", [])}
    assert len(tickers) >= 8, "Tickers view and its chips need a real spread"
    assert DATA.get("correlations"), (
        "Sources view pairs events with correlation signals"
    )
    assert any(e.get("articles") for e in EVENTS), "feed rows link to an article"


def test_record_view_starts_with_a_scoreboard() -> None:
    scored = [e for e in EVENTS if e.get("accuracy")]
    assert len(scored) >= 3, "track record must not open empty"
    assert {e["verdict"] for e in scored} >= {"INVEST", "PULL_OUT"}, "mixed outcomes"


def test_calendar_spans_enough_days() -> None:
    days = {e.get("days_ago", 0) for e in EVENTS}
    assert len(days) >= 5
    assert 0 in days, "one event is from today"


def test_resolution_is_deterministic() -> None:
    first, first_accuracy = resolve_events(EVENTS, NOW)
    second, second_accuracy = resolve_events(EVENTS, NOW)
    assert first == second
    assert first_accuracy == second_accuracy
    assert [e["timestamp"] for e in first] == [e["timestamp"] for e in second]
