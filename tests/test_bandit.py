"""Bandit shadow (scripts/backfill/bandit.py); no network."""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.backfill.bandit import Encoder, market, ridge, scored, split, verdicts


def _frame(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    tone = rng.normal(0, 3, n)
    days = pd.bdate_range("2025-09-01", periods=n // 10)
    return pd.DataFrame(
        {
            "added_utc": pd.to_datetime(np.repeat(days, 10)).tz_localize("UTC")
            + pd.Timedelta(hours=14),
            "base_date": np.repeat(days, 10),
            "avg_tone": tone,
            "mentions": rng.integers(1, 50, n),
            "ex2": tone / 100,
            "ex4": tone / 100 + rng.normal(0, 0.005, n),
        }
    )


def test_ridge_learns_tone_and_calls_score_the_called_direction(monkeypatch):
    import scripts.backfill.bandit as b

    monkeypatch.setattr(b, "CATS", {})
    monkeypatch.setattr(b, "NUMS", ["avg_tone", "mentions"])
    df = _frame()
    train, test = split(df, "2025-10-15")
    assert (
        train["base_date"].max() < pd.Timestamp("2025-10-09") <= test["base_date"].min()
    )
    enc = Encoder(train)
    pred = enc(test) @ ridge(enc(train), train["ex4"].to_numpy(), 1.0)
    c = scored(test, verdicts(pred, 0.01))
    assert set(c["verdict"]) == {"INVEST", "PULL_OUT"}
    assert c["hit2"].mean() == 1.0 and (c["g4"] > 0).mean() > 0.9


def test_market_features_use_closes_up_to_the_base_day():
    days = pd.bdate_range("2025-01-01", periods=30)
    prices = pd.concat(
        pd.DataFrame({"date": days, "ticker": t, "close": c})
        for t, c in (("SPY", 100.0), ("X", 100.0 * 1.01 ** np.arange(30)))
    )
    ev = pd.DataFrame(
        {
            "base_date": [days[25]],
            "ticker": ["X"],
            "cameo": ["042"],
            "added_utc": [(days[25] + pd.Timedelta(hours=22)).tz_localize("UTC")],
        }
    )
    row = market(ev, prices).iloc[0]
    assert round(row["pre5"], 6) == round(1.01**5 - 1, 6)
    assert round(row["atr"], 6) == 0.01 and row["root"] == "04"
    assert row["hours"] == 23  # 17:00 ET news waits for the next day's close
