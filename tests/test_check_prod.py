"""The no-new-events alert scales with the ingest interval the cron Worker passes in."""

from scripts import check_prod


def test_hourly_keeps_three_hours():
    assert check_prod.max_age_hours("1") == 3


def test_daily_waits_for_two_empty_runs():
    assert check_prod.max_age_hours("24") == 49


def test_missing_or_bad_value_assumes_daily():
    # A hand-started run carries no interval; erring long avoids a false alert email.
    assert check_prod.max_age_hours(None) == 49
    assert check_prod.max_age_hours("x") == 49
