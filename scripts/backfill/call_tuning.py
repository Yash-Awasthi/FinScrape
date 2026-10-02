"""Call tuning on live events (docs/LAYA_PLAN.md step 6), no LLM.

    python -m scripts.backfill.call_tuning pull     # Supabase + yfinance, local Parquet
    python -m scripts.backfill.call_tuning report

`pull` reads WORLDFIN_DATABASE_URL and writes data/backfill/live_calls.parquet: every
analysed event with tickers and a non-zero score, with its called-direction excess return
over SPY at +2 and +4 trading days for an INVEST and for a PULL_OUT reading (the same
`called_move` and `excess_moves` the live scorer uses). `report` splits by time, fits
thresholds and per-source and per-event-type score weights on the older half and scores
the current and the tuned rules on the newer half.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/backfill")
HORIZONS = (2, 4)
WEIGHTS = (0.0, 0.5, 1.0, 1.5, 2.0)
THRESHOLDS = (1, 2, 3, 4, 5)
CURRENT = {"invest": 3, "pull_out": 3, "w_source": {}, "w_type": {}}
MIN_GROUP = 30  # train candidates a source or event type needs to get its own weight
PURGE_DAYS = 6  # train events whose +4 day window reaches the test half are dropped


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = hits / n
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return float(mid - half), float(mid + half)


def calls(df: pd.DataFrame, rule: dict) -> pd.DataFrame:
    """Rows the rule calls, with `verdict` and `hit2` / `hit4` (NaN while open or tied)."""
    w = df["source"].map(rule["w_source"]).fillna(1.0) * df["event_type"].map(
        rule["w_type"]
    ).fillna(1.0)
    score = df["signal_score"] * w
    verdict = np.select(
        [score >= rule["invest"], score <= -rule["pull_out"]],
        ["INVEST", "PULL_OUT"],
        "",
    )
    out = df.assign(verdict=verdict)[verdict != ""]
    inv = out["verdict"] == "INVEST"
    for h in HORIZONS:
        ex = np.where(inv, out[f"inv{h}"], out[f"pull{h}"])
        out[f"hit{h}"] = np.where(np.isnan(ex) | (ex == 0), np.nan, ex > 0)
    return out


def objective(c: pd.DataFrame) -> float:
    return min(
        wilson(int(c[f"hit{h}"].sum()), int(c[f"hit{h}"].notna().sum()))[0]
        for h in HORIZONS
    )


def fit(train: pd.DataFrame, rounds: int = 2) -> dict:
    """Coordinate search for the rule whose worst-horizon Wilson lower bound is highest."""
    rule = {"invest": 3, "pull_out": 3, "w_source": {}, "w_type": {}}
    groups = [
        (key, g)
        for key, col in (("w_source", "source"), ("w_type", "event_type"))
        for g, n in train[col].value_counts().items()
        if n >= MIN_GROUP
    ]
    for _ in range(rounds):
        best = max(
            itertools.product(THRESHOLDS, THRESHOLDS),
            key=lambda ab: objective(
                calls(train, {**rule, "invest": ab[0], "pull_out": ab[1]})
            ),
        )
        rule.update(invest=best[0], pull_out=best[1])
        for key, g in groups:
            rule[key][g] = max(
                WEIGHTS,
                key=lambda w: (
                    objective(calls(train, {**rule, key: {**rule[key], g: w}})),
                    w == 1.0,
                ),
            )
    return rule


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Older and newer half of the scored events, cut at the day that best balances them
    after the purge; no day lands in both halves."""
    df = df[df["inv2"].notna() | df["pull2"].notna()]
    day = df["timestamp"].dt.tz_convert("America/New_York").dt.normalize()
    purge = pd.Timedelta(days=PURGE_DAYS)
    cut = min(
        day.unique(), key=lambda c: abs((day < c - purge).sum() - (day >= c).sum())
    )
    return df[day < cut - purge], df[day >= cut], cut


def summary(c: pd.DataFrame, h: int) -> str:
    n = int(c[f"hit{h}"].notna().sum())
    hits = int(c[f"hit{h}"].sum())
    lo, hi = wilson(hits, n)
    rate = f"{hits / n:6.1%}" if n else "     -"
    keep = "KEEP" if lo > 0.5 else ""
    return f"{rate} of {n:4d} [{lo:5.1%}, {hi:5.1%}] {keep}"


def table(test: pd.DataFrame, rules: dict[str, dict]) -> None:
    for title, col in (("overall", None), ("verdict", "verdict"),
                       ("source", "source"), ("event type", "event_type")):  # fmt: skip
        print(f"\n== {title} ==")
        for name, rule in rules.items():
            c = calls(test, rule)
            parts = [(title, c)] if col is None else list(c.groupby(col))
            for g, gc in parts:
                print(f"{name:8} {g:22} +2 {summary(gc, 2)} | +4 {summary(gc, 4)}")


def report() -> int:
    df = pd.read_parquet(DATA / "live_calls.parquet")
    train, test, cut = split(df)
    rule = fit(train)
    rules = {"current": CURRENT, "tuned": rule}
    print(f"split at {cut.date()} ET, train purge {PURGE_DAYS} days before it")
    print(f"tuned rule: {json.dumps(rule)}")
    for name, half in (("older", train), ("newer", test)):
        print(f"\n{name} half: {len(half)} scored events, {half['timestamp'].min():%d %b}"
              f" to {half['timestamp'].max():%d %b}")  # fmt: skip
        for rname, r in rules.items():
            c = calls(half, r)
            days = c["timestamp"].dt.tz_convert("America/New_York").dt.date
            per_day = days.value_counts()
            print(f"  {rname:8} decisive +2 {int(c['hit2'].notna().sum())}, "
                  f"+4 {int(c['hit4'].notna().sum())}, on {len(per_day)} days, "
                  f"busiest day {per_day.max() if len(per_day) else 0}")  # fmt: skip
            print(f"           +2 {summary(c, 2)} | +4 {summary(c, 4)}")
    table(test, rules)
    return 0


async def _events(url: str) -> pd.DataFrame:
    import asyncpg

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, signal_score, event_type, sources, tickers,
                   affected_entities
            FROM events
            WHERE signal_score <> 0 AND jsonb_array_length(tickers) > 0
              AND coalesce(key_metrics->>'prompt_variant', '') <> 'heuristic'
            ORDER BY timestamp
            """
        )
    finally:
        await conn.close()
    df = pd.DataFrame([dict(r) for r in rows])
    for col in ("sources", "tickers", "affected_entities"):
        df[col] = df[col].map(lambda v: json.loads(v) if isinstance(v, str) else v)
    return df


def pull() -> int:
    import yfinance as yf

    from finscrape.market_data import excess_moves
    from server.accuracy import called_move

    df = asyncio.run(_events(os.environ["WORLDFIN_DATABASE_URL"]))
    syms = sorted({t for ts in df["tickers"] for t in ts if t and t != "SPY"})
    start = (df["timestamp"].min() - pd.Timedelta(days=10)).date().isoformat()
    close = yf.download(
        [*syms, "SPY"], start=start, interval="1d", progress=False, auto_adjust=True
    )["Close"]
    close = close[close["SPY"].notna()]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    today = pd.Timestamp.now("America/New_York").normalize().tz_localize(None)
    close = close[close.index < today]

    cols: dict[str, list] = {f"{v}{h}": [] for v in ("inv", "pull") for h in HORIZONS}
    for r in df.itertuples():
        have = [
            t for t in dict.fromkeys(r.tickers) if t in close.columns and t != "SPY"
        ]
        ex = excess_moves(close[[*have, "SPY"]], r.timestamp)
        for v, verdict in (("inv", "INVEST"), ("pull", "PULL_OUT")):
            for h in HORIZONS:
                m = called_move(verdict, r.affected_entities or [], ex[h])
                cols[f"{v}{h}"].append(np.nan if m is None else m)
    out = df.assign(
        source=df["sources"].map(lambda s: str(s[0]).split("/")[0] if s else ""),
        **cols,
    )[["id", "timestamp", "signal_score", "event_type", "source", *cols]]
    out.to_parquet(DATA / "live_calls.parquet", index=False)
    print(f"{len(out)} events, {out['inv4'].notna().sum()} with a +4 day outcome")
    return 0


if __name__ == "__main__":
    sys.exit({"pull": pull, "report": report}[sys.argv[1]]())
