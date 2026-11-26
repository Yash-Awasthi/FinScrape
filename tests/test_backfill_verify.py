"""Backfill verification (scripts/backfill/verify.py); no database, no network."""

from scripts.backfill.verify import compare, rerun_correct, rerun_hit


def _row(rid, verdict, verdict_event=None, pct=2.5, correct=True, ex2=1.0,
         correct2=True, ex4=0.8, correct4=True):  # fmt: skip
    return {
        "id": rid,
        "event_id": rid,
        "verdict": verdict,
        "event_verdict": verdict if verdict_event is None else verdict_event,
        "price_move_pct": pct,
        "correct": correct,
        "ex2": ex2,
        "correct2": correct2,
        "ex4": ex4,
        "correct4": correct4,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def _window():
    return [
        _row(1, "INVEST"),
        # price_move_pct is signed toward the call (as `backtest` stores it).
        _row(2, "PULL_OUT", pct=3.0, ex2=2.0, ex4=1.0),
        _row(3, "OBSERVE", pct=0.3, correct=None, ex2=0.4, ex4=0.2),
    ]


def test_passing_window_is_ok_and_renders_match():
    report = compare(_window())
    assert report.ok
    assert report.rows == 3
    assert report.verdicts == {"INVEST": 1, "PULL_OUT": 1, "OBSERVE": 1}
    assert all(h.delta == 0.0 for h in report.horizons)
    text = report.render()
    assert "match" in text
    assert "INVEST 1" in text
    assert "+2 days" in text and "+4 days" in text


def test_flipped_stored_correct_is_an_outcome_mismatch():
    rows = _window()
    rows[0]["correct"] = False
    report = compare(rows)
    assert not report.ok
    assert (1, "correct") in report.outcome_mismatches


def test_stored_verdict_differs_from_event_is_a_mismatch():
    rows = _window()
    rows[0]["event_verdict"] = "PULL_OUT"
    report = compare(rows)
    assert not report.ok
    assert report.verdict_mismatches == [(1, "INVEST", "PULL_OUT")]


def test_hit_rate_drift_beyond_tolerance_is_not_ok():
    rows = _window()
    rows[0]["correct2"] = False
    report = compare(rows, tolerance=2.0)
    assert not report.ok
    assert (1, "correct2") in report.outcome_mismatches
    horizon = next(h for h in report.horizons if h.name == "+2 days")
    assert abs(horizon.delta) > report.tolerance


def test_zero_drift_is_within_tolerance():
    report = compare(_window(), tolerance=2.0)
    assert report.ok
    assert all(abs(h.delta) <= report.tolerance for h in report.horizons)


def test_null_stored_outcome_is_a_mismatch_in_a_closed_window():
    rows = _window()
    rows[1]["correct4"] = None
    report = compare(rows)
    assert not report.ok
    assert (2, "correct4") in report.outcome_mismatches


def test_rerun_hit_none_and_zero():
    assert rerun_hit(None) is None
    assert rerun_hit(0) is None
    assert rerun_hit(0.1) is True
    assert rerun_hit(-0.1) is False


def test_rerun_correct_neutral_band():
    assert rerun_correct({"price_move_pct": 0.5}) is None
    assert rerun_correct({"price_move_pct": -0.5}) is None
    assert rerun_correct({"price_move_pct": None}) is None
    assert rerun_correct({"price_move_pct": 2.0}) is True
    assert rerun_correct({"price_move_pct": -2.0}) is False
