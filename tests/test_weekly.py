"""Weekly job (plan step 8): backfill months and the live score report; no network."""

from __future__ import annotations

from datetime import date

from scripts.backfill.weekly import months
from worker.score_week import report


def test_months_cover_the_week_across_a_month_boundary():
    assert months(date(2026, 10, 3)) == ["2026-09", "2026-10"]
    assert months(date(2026, 10, 17)) == ["2026-10"]


def test_report_splits_recent_calls_and_skips_open_windows():
    rows = [
        {"verdict": "INVEST", "correct2": True, "correct4": None, "recent": True},
        {"verdict": "PULL_OUT", "correct2": False, "correct4": True, "recent": False},
    ]
    assert report(rows).splitlines() == [
        "last 14 days: +2 days 100.0% of 1, +4 days 0.0% of 0",
        "all calls: +2 days 50.0% of 2, +4 days 100.0% of 1",
    ]
