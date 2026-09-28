"""Unit tests for the load-bearing ingest logic (no DB needed).

These cover the exact behaviours that fix the live bugs: deterministic content_hash,
URL canonicalization, UTC timezone normalization, and half-open day bounds. The DB
execution path (ingest_events / ON CONFLICT) is exercised by the docker integration
verify, not here.
"""

from datetime import UTC, datetime

from server.ingest import (
    canonical_url,
    content_hash,
    day_bounds,
    normalize_subject,
    parse_timestamp,
)


def test_normalize_subject_collapses_and_lowercases():
    assert normalize_subject("  Apple   Beats\tEarnings ") == "apple beats earnings"


def test_canonical_url_strips_tracking_and_fragment_and_slash():
    a = canonical_url("https://Example.com/Path/?utm_source=x&b=2&a=1#frag")
    b = canonical_url("https://example.com/Path?a=1&b=2")
    assert a == b
    assert "utm_source" not in a and "#" not in a


def test_canonical_url_empty():
    assert canonical_url("") == ""
    assert canonical_url(None) == ""


def test_parse_timestamp_naive_assumed_utc():
    dt = parse_timestamp("2026-05-03T12:00:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_timestamp_offset_normalized_to_utc():
    # 09:00-05:00 == 14:00Z — same instant, and the UTC day is what dedup uses.
    dt = parse_timestamp("2026-05-03T09:00:00-05:00")
    assert dt.hour == 14 and dt.date().isoformat() == "2026-05-03"


def test_parse_timestamp_garbage_falls_back_to_now():
    assert parse_timestamp("not-a-date").tzinfo is not None
    assert parse_timestamp(None).tzinfo is not None


def test_content_hash_is_deterministic_and_dedupes_same_story():
    ts1 = parse_timestamp("2026-05-03T01:00:00Z")
    ts2 = parse_timestamp("2026-05-03T23:00:00Z")  # same UTC day
    h1 = content_hash("Apple beats earnings", ["https://x.com/a?utm_source=z"], ts1)
    h2 = content_hash("apple   beats   earnings", ["https://x.com/a"], ts2)
    assert h1 == h2  # subject norm + url canon + same day => same hash


def test_content_hash_differs_across_days():
    a = content_hash("S", ["https://x.com/a"], parse_timestamp("2026-05-03T23:00:00Z"))
    b = content_hash("S", ["https://x.com/a"], parse_timestamp("2026-05-04T00:00:00Z"))
    assert a != b


def test_content_hash_no_articles_uses_subject_and_day():
    h1 = content_hash("Manual signal", [], parse_timestamp("2026-05-03T00:00:00Z"))
    h2 = content_hash("manual signal", None, parse_timestamp("2026-05-03T12:00:00Z"))
    assert h1 == h2


def test_day_bounds_half_open():
    start, end = day_bounds("2026-05-03")
    assert start == datetime(2026, 5, 3, tzinfo=UTC)
    assert end == datetime(2026, 5, 4, tzinfo=UTC)
    # a 23:59:59Z event is inside [start, end); midnight next day is excluded
    assert start <= parse_timestamp("2026-05-03T23:59:59Z") < end
    assert not (parse_timestamp("2026-05-04T00:00:00Z") < end)
