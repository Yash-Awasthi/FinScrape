"""Phase 11 seed — pure resolution + dataset sanity (no DB needed)."""

from __future__ import annotations

from datetime import UTC, datetime

from server.seed.loader import load_dataset, resolve_events

NOW = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)


def test_resolve_events_sets_absolute_utc_timestamp():
    raw = [
        {
            "days_ago": 2,
            "hour": 9,
            "subject": "x",
            "verdict": "INVEST",
            "tickers": ["A"],
        }
    ]
    events, _ = resolve_events(raw, NOW)
    assert events[0]["timestamp"] == "2026-06-27T09:00:00+00:00"
    # seed-only keys are stripped; real fields survive
    assert "days_ago" not in events[0] and "hour" not in events[0]
    assert events[0]["subject"] == "x"


def test_resolve_events_extracts_accuracy_and_honors_skip():
    raw = [
        {
            "days_ago": 0,
            "subject": "keep",
            "verdict": "INVEST",
            "accuracy": {"price_move_pct": 2.0, "correct": True},
        },
        {"days_ago": 1, "subject": "drop", "verdict": "PULL_OUT", "_skip": True},
    ]
    events, acc = resolve_events(raw, NOW)
    assert [e["subject"] for e in events] == ["keep"]
    assert acc["keep"]["correct"] is True
    assert "accuracy" not in events[0]


def test_dataset_is_well_formed():
    data = load_dataset()
    events = data["events"]
    assert len(events) >= 12, "demo should be full of signal"
    verdicts = {e["verdict"] for e in events}
    assert {"INVEST", "PULL_OUT", "OBSERVE", "CAUTIOUS"} <= verdicts, (
        "all verdict classes present"
    )
    # every event is geolocated (globe) and the resolver produces valid timestamps
    assert all(
        isinstance(e.get("lat"), (int, float))
        and isinstance(e.get("lon"), (int, float))
        for e in events
    )
    resolved, _ = resolve_events(events, NOW)
    assert all(r["timestamp"].endswith("+00:00") for r in resolved)
    # correlations drive the breaking-news/correlation panels
    assert len(data["correlations"]) >= 1
