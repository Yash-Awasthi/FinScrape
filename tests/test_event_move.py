import datetime as dt

import pandas as pd

from finscrape.market_data import window_move

CLOSES = pd.Series(
    [100.0, 102.0, 99.0, 90.0],
    index=pd.to_datetime(["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29"]),
)


def test_move_runs_from_close_before_the_event_day():
    at = dt.datetime(2026, 9, 25, 15, tzinfo=dt.UTC)
    assert window_move(CLOSES, at, 24) == -1.0  # 100 on the 24th to 99 on the 28th


def test_weekend_event_scores_on_next_trading_day():
    at = dt.datetime(2026, 9, 26, 12, tzinfo=dt.UTC)
    assert round(window_move(CLOSES, at, 24), 2) == -2.94  # 102 to 99


def test_unscored_until_the_window_closes():
    at = dt.datetime(2026, 9, 29, 9, tzinfo=dt.UTC)
    assert window_move(CLOSES, at, 24) is None


def test_excess_runs_from_the_last_close_before_the_news():
    from finscrape.market_data import excess_moves

    days = pd.to_datetime(
        [
            "2026-09-22",
            "2026-09-23",
            "2026-09-24",
            "2026-09-25",
            "2026-09-28",
            "2026-09-29",
        ]
    )
    closes = pd.DataFrame(
        {
            "XOM": [100.0, 101, 102, 103, 104, 105],
            "SPY": [100.0, 100, 101, 101, 101, 101],
        },
        index=days,
    )
    # 11:00 ET on the 23rd: before the close, so the base is the 22nd's close.
    before = excess_moves(closes, dt.datetime(2026, 9, 23, 15, tzinfo=dt.UTC))
    assert round(before[2]["XOM"], 6) == round((102 / 100 - 1 - 0.01) * 100, 6)
    assert round(before[4]["XOM"], 6) == round((104 / 100 - 1 - 0.01) * 100, 6)
    # 17:00 ET on the 23rd: after the close, so the base is the 23rd itself.
    after = excess_moves(closes, dt.datetime(2026, 9, 23, 21, tzinfo=dt.UTC))
    assert round(after[2]["XOM"], 6) == round((103 / 101 - 1 - 0.01) * 100, 6)
    # +4 needs the 29th's close and the 30th's for a base on the 24th: not there yet.
    late = excess_moves(closes, dt.datetime(2026, 9, 24, 21, tzinfo=dt.UTC))
    assert "XOM" in late[2] and late[4] == {}
