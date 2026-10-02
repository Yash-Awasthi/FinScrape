"""Phase 7: accuracy correctness rule + aggregation (pure, offline).

The backtest DB path (server.accuracy.backtest) is covered by the docker integration run.
"""
import pytest

from finscrape.accuracy import calibration
from server.accuracy import aggregate, verdict_outcome


def test_verdict_outcome_directional():
    assert verdict_outcome("INVEST", 2.0) == "correct"
    assert verdict_outcome("INVEST", -2.0) == "incorrect"
    assert verdict_outcome("INVEST", 0.5) == "neutral"  # below ±1% threshold
    assert verdict_outcome("PULL_OUT", -2.0) == "correct"
    assert verdict_outcome("PULL_OUT", 2.0) == "incorrect"


def test_verdict_outcome_nondirectional():
    assert verdict_outcome("OBSERVE", 5.0) == "neutral"
    assert verdict_outcome("CAUTIOUS", -5.0) == "neutral"


def test_aggregate_hit_rate_and_equity_curve():
    rows = [
        {"verdict": "INVEST", "correct": True, "checked_at": "2026-01-01T00:00:00"},
        {"verdict": "INVEST", "correct": False, "checked_at": "2026-01-02T00:00:00"},
        {"verdict": "PULL_OUT", "correct": True, "checked_at": "2026-01-03T00:00:00"},
        {"verdict": "OBSERVE", "correct": None, "checked_at": "2026-01-04T00:00:00"},  # unscored
    ]
    agg = aggregate(rows)
    assert agg["total"] == 4 and agg["scored"] == 3
    assert agg["hits"] == 2
    assert agg["hit_rate"] == round(2 / 3, 3)
    assert agg["by_verdict"]["INVEST"] == {"hits": 1, "total": 2, "hit_rate": 0.5}
    # cumulative +1 / -1 in time order: +1, 0, +1
    assert agg["equity_curve"] == [1, 0, 1]


def test_aggregate_empty():
    agg = aggregate([])
    assert agg["hit_rate"] == 0.0 and agg["equity_curve"] == []


def test_calibration_all_correct_high_confidence():
    rows = [{"confidence": 0.9, "correct": True} for _ in range(10)]
    calib = calibration(rows)
    assert calib["brier"] == pytest.approx(0.01, abs=1e-6)


def test_calibration_all_wrong_high_confidence():
    rows = [{"confidence": 0.9, "correct": False} for _ in range(10)]
    calib = calibration(rows)
    assert calib["brier"] == pytest.approx(0.81, abs=1e-6)


def test_calibration_half_confidence_always_025_brier():
    correct_rows = [{"confidence": 0.5, "correct": True} for _ in range(5)]
    wrong_rows = [{"confidence": 0.5, "correct": False} for _ in range(5)]
    assert calibration(correct_rows)["brier"] == 0.25
    assert calibration(wrong_rows)["brier"] == 0.25


def test_calibration_bucket_counts_sum_to_rows():
    rows = [
        {"confidence": 0.1, "correct": True},
        {"confidence": 0.3, "correct": False},
        {"confidence": 0.6, "correct": True},
        {"confidence": 0.9, "correct": True},
        {"confidence": 0.99, "correct": False},
    ]
    calib = calibration(rows)
    assert sum(calib["buckets"].values()) == len(rows)


def test_calibration_empty():
    calib = calibration([])
    assert calib["brier"] is None
    assert sum(calib["buckets"].values()) == 0


def test_aggregate_includes_calibration():
    rows = [
        {"verdict": "INVEST", "correct": True, "checked_at": "2026-01-01T00:00:00", "confidence": 0.9},
        {"verdict": "PULL_OUT", "correct": False, "checked_at": "2026-01-02T00:00:00", "confidence": 0.9},
    ]
    agg = aggregate(rows)
    assert agg["calibration"]["brier"] == pytest.approx((0.01 + 0.81) / 2, abs=1e-6)
    assert sum(agg["calibration"]["buckets"].values()) == 2


def _pool(event: dict, written: list):
    class Pool:
        async def fetch(self, *args):
            return [event]

        async def fetchval(self, query, *args):
            written.append(args)
            return 1

    return Pool()


def test_backtest_scores_the_window_after_each_event():
    import asyncio
    from datetime import UTC, datetime

    from server.accuracy import backtest

    at = datetime(2026, 9, 25, 15, tzinfo=UTC)
    written: list[tuple] = []
    event = {"id": 7, "verdict": "INVEST", "tickers": ["XOM"], "timestamp": at,
             "affected_entities": []}
    calls = []

    def fetcher(tickers, when, hours):
        calls.append((tickers, when, hours))
        return {"XOM": 2.5}

    assert asyncio.run(backtest(_pool(event, written), fetcher)) == 1
    assert calls == [(["XOM"], at, 24)]
    assert written == [(7, "XOM", "INVEST", 2.5, True)]


def test_each_ticker_is_scored_in_the_direction_the_analysis_gave_it():
    """A PULL_OUT on a conflict story names defence stocks as winners; their rise
    confirms the call instead of counting against it."""
    import asyncio
    from datetime import UTC, datetime

    from server.accuracy import backtest

    written: list[tuple] = []
    event = {
        "id": 9,
        "verdict": "PULL_OUT",
        "tickers": ["RTX", "ZIM"],
        "timestamp": datetime(2026, 9, 25, 15, tzinfo=UTC),
        "affected_entities": [{"name": "RTX Corp", "ticker": "RTX", "impact": "positive"}],
    }
    moves = {"RTX": 3.0, "ZIM": -2.0}  # the winner rose, the unlabelled one fell
    assert asyncio.run(backtest(_pool(event, written), lambda t, a, h: moves)) == 1
    event_id, ticker, verdict, called_move, correct = written[0]
    assert (event_id, verdict, correct) == (9, "PULL_OUT", True)
    assert called_move == 2.5  # mean of +3.0 (up, as called) and +2.0 (down, as called)


def test_vs_spy_scores_each_call_against_the_market():
    """A PULL_OUT whose ticker lagged SPY is a hit even when the ticker itself rose."""
    import asyncio
    from datetime import UTC, datetime

    from server.accuracy import score_vs_spy

    row = {
        "id": 3,
        "verdict": "PULL_OUT",
        "tickers": ["RTX", "ZIM"],
        "timestamp": datetime(2026, 9, 21, 14, tzinfo=UTC),
        "affected_entities": [{"ticker": "RTX", "impact": "positive"}],
    }
    updates: list[tuple] = []

    class Pool:
        async def fetch(self, *args):
            return [row]

        async def execute(self, query, *args):
            updates.append(args)

    # RTX beat SPY (+1.0, called up) and ZIM lagged it (-3.0, called down): both right.
    excess = {2: {"RTX": 1.0, "ZIM": -3.0}, 4: {"RTX": -2.0}}
    assert asyncio.run(score_vs_spy(Pool(), lambda t, a: excess)) == 1
    assert updates == [(3, 2.0, -2.0, True, False)]


def test_vs_spy_leaves_an_open_window_unscored():
    import asyncio
    from datetime import UTC, datetime

    from server.accuracy import score_vs_spy

    row = {
        "id": 4,
        "verdict": "INVEST",
        "tickers": ["XOM"],
        "affected_entities": [],
        "timestamp": datetime(2026, 9, 29, 14, tzinfo=UTC),
    }
    updates: list[tuple] = []

    class Pool:
        async def fetch(self, *args):
            return [row]

        async def execute(self, query, *args):
            updates.append(args)

    assert asyncio.run(score_vs_spy(Pool(), lambda t, a: {2: {"XOM": 0.5}, 4: {}})) == 1
    assert updates == [(4, 0.5, None, True, None)]


def test_vs_spy_summary_counts_only_closed_windows():
    from server.accuracy import vs_spy_summary

    rows = [
        {"verdict": "PULL_OUT", "correct2": True, "correct4": True},
        {"verdict": "PULL_OUT", "correct2": False, "correct4": None},
        {"verdict": "INVEST", "correct2": True, "correct4": False},
        {"verdict": "INVEST", "correct2": None, "correct4": None},
    ]
    s = vs_spy_summary(rows)
    assert (s["d2"]["scored"], s["d2"]["hits"], s["d2"]["hit_rate"]) == (3, 2, 0.667)
    assert (s["d4"]["scored"], s["d4"]["hits"]) == (2, 1)
    assert s["d4"]["by_verdict"]["PULL_OUT"] == {"hits": 1, "total": 1, "hit_rate": 1.0}
