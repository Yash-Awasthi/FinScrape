"""Call tuning (scripts/backfill/call_tuning.py); no network."""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.backfill.call_tuning import CURRENT, calls, fit, split, wilson


def _events(n_days: int = 40) -> pd.DataFrame:
    rows = []
    for d in range(n_days):
        for score, src in ((3, "gdelt"), (-3, "gdelt"), (3, "noise"), (-3, "noise")):
            good = 1.0 if src == "gdelt" else (1.0 if d % 2 else -1.0)
            rows.append(
                {
                    "timestamp": pd.Timestamp("2026-07-01 14:00", tz="UTC")
                    + pd.Timedelta(days=d),
                    "signal_score": score,
                    "event_type": "geopolitical_event",
                    "source": src,
                    "inv2": good if score > 0 else -good,
                    "inv4": good if score > 0 else -good,
                    "pull2": good if score < 0 else -good,
                    "pull4": np.nan if score < 0 else -good,
                }
            )
    return pd.DataFrame(rows)


def test_wilson_matches_known_interval():
    lo, hi = wilson(50, 100)
    assert round(lo, 3) == 0.404 and round(hi, 3) == 0.596


def test_calls_score_the_called_direction_and_skip_open_windows():
    c = calls(_events(1), CURRENT)
    assert c["hit2"].tolist() == [1.0, 1.0, 0.0, 0.0]
    assert c.loc[c["verdict"] == "PULL_OUT", "hit4"].isna().all()


def test_fit_mutes_the_coin_flip_source_and_split_keeps_days_apart():
    train, test, cut = split(_events())
    assert train["timestamp"].max() < cut.tz_convert("UTC") <= test["timestamp"].min()
    rule = fit(train)
    assert rule["w_source"] == {"gdelt": 1.0, "noise": 0.0}
