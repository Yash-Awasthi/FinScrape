"""Bandit shadow on the backfill (docs/LAYA_PLAN.md step 7), no LLM.

    python -m scripts.backfill.bandit

Single-company events with a +4 day outcome. Actions INVEST / PULL_OUT / OBSERVE earn
ex4, -ex4 and 0. Every action's reward is known offline, so the per-action linear models
reduce to one ridge regression on ex4: INVEST's model is the fit, PULL_OUT's its negation.
The bandit calls when the predicted |ex4| clears a margin; ridge strength and margin are
picked on the last train quarter, then the model is refit on the whole train split.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.backfill.call_tuning import wilson

DATA = Path("data/backfill")
TRAIN = ("2023-10-01", "2025-09-30")
TEST = "2025-10-01"
VALID = "2025-07-01"  # last train quarter, for picking ridge strength and margin
PURGE = 4  # trading days: train rows whose +4 window reaches past their cut are dropped
CATS = {"cameo": 200, "root": 1, "quad_class": 1, "sector": 1, "country": 300,
        "domain": 300, "weekday": 1}  # fmt: skip  # min train rows for a category level
NUMS = ["goldstein", "mentions", "avg_tone", "pre5", "pre20", "atr", "hours"]
LAMBDAS = (1.0, 100.0, 10_000.0)
COVERAGE = (0.5, 0.2, 0.1, 0.05, 0.02, 0.01)  # share of validation rows called
TONE = (0.0, 1.0, 2.0, 3.0, 5.0, 7.0)


def market(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Ticker's state at the base close: prior 5 and 20 day excess over SPY, ATR% (from
    closes: mean absolute daily move over 14 days), weekday, hours to the next close."""
    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    days = close.index.values
    m = close.to_numpy()
    b = close.index.get_indexer(events["base_date"])
    col = close.columns.get_indexer(events["ticker"])
    spy = close.columns.get_loc("SPY")

    def back(k: int) -> np.ndarray:
        ok = b >= k
        j = np.where(ok, b - k, 0)
        r = m[b, col] / m[j, col] - m[b, spy] / m[j, spy]
        return np.where(ok, r, np.nan)

    daily = np.abs(close.pct_change(fill_method=None)).rolling(14).mean().to_numpy()
    et = events["added_utc"].dt.tz_convert("America/New_York")
    nxt = np.minimum(b + 1, len(days) - 1)
    close_at = pd.Series(pd.to_datetime(days[nxt]) + pd.Timedelta(hours=16))
    close_at = close_at.dt.tz_localize("America/New_York").set_axis(et.index)
    hours = (close_at - et).dt.total_seconds().to_numpy() / 3600
    return events.assign(
        pre5=back(5),
        pre20=back(20),
        atr=daily[b, col],
        weekday=et.dt.day_name().to_numpy(),
        hours=np.where(b + 1 < len(days), hours, np.nan),
        root=events["cameo"].str[:2],
    )


def load() -> pd.DataFrame:
    cols = ["event_id", "added_utc", "domain", "cameo", "quad_class", "goldstein",
            "mentions", "avg_tone", "country", "tickers"]  # fmt: skip
    one = [("n_companies", "==", 1)]
    files = sorted((DATA / "events").glob("*.parquet"))
    ev = pd.concat(pd.read_parquet(f, columns=cols, filters=one) for f in files)
    ev = ev.assign(ticker=ev["tickers"].str[0]).drop(columns="tickers")
    out = pd.read_parquet(DATA / "outcomes.parquet").dropna(subset=["ex4"])
    uni = pd.read_parquet(DATA / "universe.parquet", columns=["ticker", "sector"])
    df = ev.merge(out, on=["event_id", "ticker"]).merge(uni, on="ticker")
    df = market(df, pd.read_parquet(DATA / "prices.parquet"))
    return df.sort_values("added_utc").reset_index(drop=True)


def split(df: pd.DataFrame, cut: str, start: str | None = None, end: str | None = None):
    """Rows before `cut` (purged so no +4 window crosses it) and from `cut` on."""
    day = df["added_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    days = np.sort(df["base_date"].unique())
    last_base = days[np.searchsorted(days, np.datetime64(cut)) - PURGE - 1]
    lo = day >= start if start else True
    hi = day < (pd.Timestamp(end) + pd.Timedelta(days=1)) if end else True
    before = df[lo & (day < cut) & (df["base_date"] <= last_base)]
    return before, df[(day >= cut) & hi]


class Encoder:
    """One-hot categories seen often enough in train, standardised numbers."""

    def __init__(self, train: pd.DataFrame):
        self.levels = {
            c: [k for k, n in train[c].value_counts().items() if n >= CATS[c]]
            for c in CATS
        }
        num = self._num(train)
        self.mean, self.std = np.nanmean(num, 0), np.nanstd(num, 0) + 1e-12

    @staticmethod
    def _num(df: pd.DataFrame) -> np.ndarray:
        num = df[NUMS].to_numpy(float)
        num[:, NUMS.index("mentions")] = np.log1p(num[:, NUMS.index("mentions")])
        return num

    def __call__(self, df: pd.DataFrame) -> np.ndarray:
        num = np.clip((self._num(df) - self.mean) / self.std, -5, 5)
        parts = [np.ones((len(df), 1)), np.nan_to_num(num)]
        for c, levels in self.levels.items():
            v = df[c].where(df[c].isin(levels))
            idx = pd.Categorical(v, categories=levels).codes
            hot = np.zeros((len(df), len(levels)), dtype=np.float32)
            hot[idx >= 0, idx[idx >= 0]] = 1
            parts.append(hot)
        return np.hstack(parts)


def ridge(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    reg = lam * np.eye(x.shape[1])
    reg[0, 0] = 0
    return np.linalg.solve(x.T @ x + reg, x.T @ y)


def target(df: pd.DataFrame) -> np.ndarray:
    # ponytail: 1/99% winsorised so a few takeover jumps don't set the slope.
    lo, hi = df["ex4"].quantile([0.01, 0.99])
    return df["ex4"].clip(lo, hi).to_numpy()


def verdicts(pred: np.ndarray, margin: float) -> np.ndarray:
    return np.select([pred > margin, pred < -margin], ["INVEST", "PULL_OUT"], "")


def scored(df: pd.DataFrame, verdict: np.ndarray) -> pd.DataFrame:
    """Called rows, with called-direction excess `g2` / `g4` and hits (NaN on ties)."""
    c = df.assign(verdict=verdict)[verdict != ""]
    sign = np.where(c["verdict"] == "INVEST", 1.0, -1.0)
    for h in (2, 4):
        g = sign * c[f"ex{h}"].to_numpy()
        c[f"g{h}"] = g
        c[f"hit{h}"] = np.where(np.isnan(g) | (g == 0), np.nan, g > 0)
    return c


def objective(c: pd.DataFrame) -> float:
    return min(
        wilson(int(c[f"hit{h}"].sum()), int(c[f"hit{h}"].notna().sum()))[0]
        for h in (2, 4)
    )


def tone_rule(df: pd.DataFrame, t: float, gold: bool) -> np.ndarray:
    up, down = df["avg_tone"] >= t, df["avg_tone"] <= -t
    if gold:
        up, down = up & (df["goldstein"] > 0), down & (df["goldstein"] < 0)
    if t == 0:
        up, down = up & (df["avg_tone"] > 0), down & (df["avg_tone"] < 0)
    return np.select([up, down], ["INVEST", "PULL_OUT"], "")


def fit(df: pd.DataFrame) -> tuple[Encoder, np.ndarray, float, dict]:
    early, valid = split(df, VALID, end=TRAIN[1])
    enc = Encoder(early)
    x, xv = enc(early), enc(valid)
    best = (-1.0, LAMBDAS[0], 0.0)
    for lam in LAMBDAS:
        pv = xv @ ridge(x, target(early), lam)
        for cov in COVERAGE:
            margin = float(np.quantile(np.abs(pv), 1 - cov))
            best = max(best, (objective(scored(valid, verdicts(pv, margin))), lam, cov))
    _, lam, cov = best
    train, _ = split(df, TEST, start=TRAIN[0])
    enc = Encoder(train)
    x = enc(train)
    w = ridge(x, target(train), lam)
    # Margin keeps the validation call rate: that quantile of |pred| on the train split.
    margin = float(np.quantile(np.abs(x @ w), 1 - cov))
    tone = max(
        itertools.product(TONE, (False, True)),
        key=lambda tg: objective(scored(train, tone_rule(train, *tg))),
    )
    return enc, w, margin, {"lambda": lam, "coverage": cov, "tone": tone}


def line(c: pd.DataFrame, n_days: int) -> str:
    out = []
    for h in (2, 4):
        n, hits = int(c[f"hit{h}"].notna().sum()), int(c[f"hit{h}"].sum())
        lo, hi = wilson(hits, n)
        rate = f"{hits / n:5.1%}" if n else "    -"
        out.append(f"+{h} {rate} [{lo:5.1%},{hi:5.1%}]{'*' if lo > 0.5 else ' '}")
    mean = c["g4"].mean() * 1e4 if len(c) else 0.0
    return f"n {len(c):6d} {' '.join(out)} ex4 {mean:+6.1f}bp/call {len(c) / n_days:7.1f}/day"


def report() -> int:
    df = load()
    enc, w, margin, picked = fit(df)
    train, test = split(df, TEST, start=TRAIN[0])
    pred = enc(test) @ w
    n_days = test["base_date"].nunique()
    print(f"single-company events with ex4: train {len(train):,} "
          f"({train['added_utc'].min():%Y-%m-%d} to {train['added_utc'].max():%Y-%m-%d}), "
          f"test {len(test):,} ({test['added_utc'].min():%Y-%m-%d} to "
          f"{test['added_utc'].max():%Y-%m-%d}, {n_days} base days)")  # fmt: skip
    print(
        f"picked on validation {VALID}..{TRAIN[1]}: {picked}, margin {margin * 1e4:.1f}bp"
    )
    print(
        f"features {len(w)}; test corr(pred, ex4) {np.corrcoef(pred, test['ex4'])[0, 1]:+.4f}"
    )
    rules = {
        "bandit": verdicts(pred, margin),
        "OBSERVE": np.full(len(test), ""),
        "INVEST": np.full(len(test), "INVEST"),
        "PULL_OUT": np.full(len(test), "PULL_OUT"),
        "tone": tone_rule(test, *picked["tone"]),
    }
    calls = {k: scored(test, v) for k, v in rules.items()}
    print("\n== test, overall (* = Wilson 95% lower bound above 50%) ==")
    for k, c in calls.items():
        print(f"{k:9}{line(c, n_days)}")
    print(
        "\n== test, one call per ticker and base day (majority verdict, mean excess) =="
    )
    for k, c in calls.items():
        if c.empty:
            continue
        g = c.groupby(["ticker", "base_date"])
        one = g.agg(verdict=("verdict", lambda v: v.mode()[0]), ex2=("ex2", "first"),
                    ex4=("ex4", "first")).reset_index()  # fmt: skip
        print(f"{k:9}{line(scored(one, one['verdict'].to_numpy()), n_days)}")
    print("\n== bandit calls by verdict ==")
    for v, c in calls["bandit"].groupby("verdict"):
        print(f"{v:9}{line(c, n_days)}")
    print("\n== test, by sector ==")
    for sector in sorted(test["sector"].unique()):
        for k in ("bandit", "INVEST", "tone"):
            c = calls[k][calls[k]["sector"] == sector]
            print(f"{sector:14}{k:9}{line(c, n_days)}")
    per_day = calls["bandit"]["base_date"].value_counts()
    print(f"\nbandit calls land on {len(per_day)} of {n_days} base days; busiest "
          f"{per_day.max()} calls on {per_day.idxmax():%Y-%m-%d}; top 10% of days hold "
          f"{per_day.nlargest(max(1, len(per_day) // 10)).sum() / per_day.sum():.0%}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(report())
