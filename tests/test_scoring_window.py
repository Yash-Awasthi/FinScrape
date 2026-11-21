"""The scoring window: trading days, holidays, half-days, DST and after-close news.

Every case fixes the calendar by hand, because the bugs this guards against are calendar
bugs: a +2 horizon landing on a closed day, a holiday row that does not exist, a
spring-forward session that shifts by an hour, or an entry at a price nobody could trade
(plan m1.4.2).

Convention, so the numbers below can be checked by hand:

* an intraday event on a trading day is entered at the **previous** session's close (the
  price before the news) and its horizons count from the event day's session;
* news at/after the close, or on a closed day, is entered at the **next session's open**
  and its horizons count from that session.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from finscrape.market_data import excess_moves, window_move

# Sessions around US Thanksgiving 2026: Thu 26 Nov is closed (no row at all), Fri 27 Nov is
# a half-day that closes at 13:00 ET. Holidays have no row, exactly as a feed returns them.
SESSIONS = [
    "2026-11-24",  # Tue  pos 0
    "2026-11-25",  # Wed  pos 1
    "2026-11-27",  # Fri  pos 2, half-day
    "2026-11-30",  # Mon  pos 3
    "2026-12-01",  # Tue  pos 4
]
CLOSE_VALUES = [100.0, 101.0, 102.0, 103.0, 104.0]


def _frame(closes: list[float] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    values = closes if closes is not None else CLOSE_VALUES
    index = pd.to_datetime(SESSIONS)
    body = {"XOM": values, "SPY": [50.0] * len(values)}  # flat SPY: excess == raw move
    return pd.DataFrame(body, index=index), pd.DataFrame(body, index=index)


CLOSES, OPENS = _frame()


def test_plus_two_and_four_skip_the_holiday_and_land_on_sessions():
    # 11:00 ET Wednesday 25 Nov: entered at Tuesday's close (100), so +2 is Friday the 27th
    # (102, the half-day close) and +4 is Tuesday 1 Dec (104). Thanksgiving has no row and
    # is never a horizon.
    out = excess_moves(CLOSES, dt.datetime(2026, 11, 25, 16, tzinfo=dt.UTC), OPENS)

    assert out[2]["XOM"] == pytest.approx((102 / 100 - 1) * 100, abs=1e-6)
    assert out[4]["XOM"] == pytest.approx((104 / 100 - 1) * 100, abs=1e-6)


def test_a_weekend_event_enters_at_monday_open_not_fridays_close():
    closes, opens = _frame()
    # Friday 27 Nov closes at 102; Monday 30 Nov opens at 105 after the weekend news.
    opens.loc[pd.Timestamp("2026-11-30"), "XOM"] = 105.0
    out = excess_moves(closes, dt.datetime(2026, 11, 28, 17, tzinfo=dt.UTC), opens)

    # Entered at Monday's open 105: +2 is the close of the session after it (1 Dec, 104),
    # and +4 needs a later session that does not exist yet.
    assert out[2]["XOM"] == pytest.approx((104 / 105 - 1) * 100, abs=1e-6)
    assert out[4] == {}


def test_after_the_close_enters_at_the_next_open_not_that_close():
    closes, opens = _frame()
    opens.loc[pd.Timestamp("2026-11-27"), "XOM"] = 101.5  # session after the 25th
    out = excess_moves(closes, dt.datetime(2026, 11, 25, 22, tzinfo=dt.UTC), opens)

    # 17:00 ET on the 25th: entry is the 27th's open (101.5), +2 is the 30th's close (103).
    assert out[2]["XOM"] == pytest.approx((103 / 101.5 - 1) * 100, abs=1e-6)
    assert out[4] == {}


def test_after_the_close_without_an_open_bar_is_unscored():
    # The 25th's close was history by the time the news broke, so scoring from it would
    # bank a gap nobody could trade. No Open bar means no score, not a wrong score.
    assert excess_moves(CLOSES, dt.datetime(2026, 11, 25, 22, tzinfo=dt.UTC)) == {2: {}, 4: {}}


def test_dst_boundary_does_not_shift_the_entry_day():
    # Spring forward on Sun 8 Mar 2026. A 08:00 ET Monday event is intraday on the 9th; a
    # 20:30 ET Monday event is after that session's close. Same two dates, one hour apart.
    index = pd.to_datetime(["2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11"])
    body = {"XOM": [100.0, 102.0, 103.0, 104.0], "SPY": [50.0] * 4}
    closes, opens = pd.DataFrame(body, index=index), pd.DataFrame(body, index=index)

    intraday = excess_moves(closes, dt.datetime(2026, 3, 9, 12, tzinfo=dt.UTC), opens)
    assert intraday[2]["XOM"] == pytest.approx((103 / 100 - 1) * 100, abs=1e-6)

    late = excess_moves(closes, dt.datetime(2026, 3, 10, 0, 30, tzinfo=dt.UTC), opens)
    assert late[2]["XOM"] == pytest.approx((104 / 103 - 1) * 100, abs=1e-6)


def test_a_nan_close_excludes_the_ticker_instead_of_scoring_it_as_zero():
    closes, opens = _frame()
    closes.loc[pd.Timestamp("2026-11-27"), "XOM"] = float("nan")

    out = excess_moves(closes, dt.datetime(2026, 11, 25, 16, tzinfo=dt.UTC), opens)

    # +2 lands on the missing 27 Nov close, so that horizon has no XOM row at all — it is
    # absent, never a 0% move and never a miss.
    assert out[2] == {}
    assert out[4]["XOM"] == pytest.approx((104 / 100 - 1) * 100, abs=1e-6)


def test_a_half_day_close_is_a_valid_horizon_close():
    # 12:30 ET on the half-day is intraday: entered at the 25th's close (101), +2 is the
    # 30th's close (103) because the half-day session itself is the +1.
    out = excess_moves(CLOSES, dt.datetime(2026, 11, 27, 17, 30, tzinfo=dt.UTC), OPENS)
    assert out[2]["XOM"] == pytest.approx((103 / 101 - 1) * 100, abs=1e-6)
    assert out[4] == {}


def test_window_move_uses_the_close_before_the_event_day_and_refuses_open_windows():
    closes = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.to_datetime(["2026-11-25", "2026-11-30", "2026-12-01"]),
    )
    # The Thanksgiving gap does not matter: the day before Fri 27 Nov is Wed 25 Nov, and the
    # next session after it is Mon 30 Nov.
    assert window_move(closes, dt.datetime(2026, 11, 27, 16, tzinfo=dt.UTC), 24) == pytest.approx(
        1.0
    )
    # An open window is None, not 0%: the call is not scored yet.
    assert window_move(closes, dt.datetime(2026, 12, 1, 16, tzinfo=dt.UTC), 24) is None
