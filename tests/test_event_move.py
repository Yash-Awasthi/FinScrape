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
