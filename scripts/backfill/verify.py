"""Backfill verification: re-score a closed window and compare with the stored record.

`python -m scripts.backfill.verify --days 180 --settle-days 7`

Reads the closed `accuracy_outcomes` rows for a historical window, re-derives each
outcome from the record's own frozen evidence (`price_move_pct`, `ex2`, `ex4`) with the
live rules from `server.accuracy`, then asserts the stored verdict distribution and hit
rates agree within a tolerance. Read-only; writes nothing. The price moves are the
frozen record, so this re-runs the classification, not the market download: it proves
the stored verdicts and outcomes still follow the current rule, not today's prices.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

from server.accuracy import verdict_outcome

FIELDS = ("correct", "correct2", "correct4")
HORIZONS = (("price", "correct"), ("+2 days", "correct2"), ("+4 days", "correct4"))


def rerun_correct(row: dict) -> bool | None:
    """Re-derive the price-move outcome from the signed move, as `backtest` does."""
    pct = row.get("price_move_pct")
    if pct is None:
        return None
    outcome = verdict_outcome("INVEST", pct)
    if outcome == "neutral":
        return None
    return outcome == "correct"


def rerun_hit(ex: float | None) -> bool | None:
    """Re-derive an excess-return hit, as `score_vs_spy` does."""
    if ex is None or ex == 0:
        return None
    return ex > 0


def _rerun(row: dict, field: str) -> bool | None:
    if field == "correct":
        return rerun_correct(row)
    return rerun_hit(row.get("ex2" if field == "correct2" else "ex4"))


@dataclass(frozen=True)
class Horizon:
    name: str
    stored_hits: int
    stored_n: int
    rerun_hits: int
    rerun_n: int
    tolerance: float

    @property
    def stored_rate(self) -> float:
        return 100.0 * self.stored_hits / self.stored_n if self.stored_n else 0.0

    @property
    def rerun_rate(self) -> float:
        return 100.0 * self.rerun_hits / self.rerun_n if self.rerun_n else 0.0

    @property
    def delta(self) -> float:
        """Rerun rate minus stored rate, in percentage points."""
        return self.rerun_rate - self.stored_rate


@dataclass(frozen=True)
class Report:
    window_days: int
    settle_days: int
    rows: int
    verdicts: dict[str, int]
    horizons: tuple[Horizon, ...]
    verdict_mismatches: list[tuple[int, str, str]]
    outcome_mismatches: list[tuple[int, str]]
    tolerance: float

    @property
    def ok(self) -> bool:
        return (
            not self.verdict_mismatches
            and not self.outcome_mismatches
            and all(abs(h.delta) <= self.tolerance for h in self.horizons)
        )

    def render(self) -> str:
        lines = [
            (
                f"window: closed rows {self.settle_days}d to {self.window_days}d old; "
                f"{self.rows} rows"
            ),
            "",
            f"{'horizon':<10}{'n':>6}{'stored':>9}{'rerun':>9}{'delta':>9}",
        ]
        for h in self.horizons:
            lines.append(
                f"{h.name:<10}{h.stored_n:>6}{h.stored_rate:>8.1f}%"
                f"{h.rerun_rate:>8.1f}%{h.delta:>+8.1f}pp"
            )
        dist = ", ".join(f"{k} {v}" for k, v in sorted(self.verdicts.items()))
        lines.extend(["", f"verdicts: {dist or 'none'}"])
        if self.verdict_mismatches:
            lines.append("verdict mismatches:")
            lines.extend(
                f"  outcome {i}: stored {s}, event {e}"
                for i, s, e in self.verdict_mismatches
            )
        if self.outcome_mismatches:
            lines.append("outcome mismatches:")
            lines.extend(f"  outcome {i}: {f}" for i, f in self.outcome_mismatches)
        verdict = "all checks match" if self.ok else "MISMATCH"
        lines.extend(["", f"{verdict} within {self.tolerance:.1f}pp tolerance"])
        return "\n".join(lines)


def _horizon(name: str, rows: list[dict], field: str, tolerance: float) -> Horizon:
    pairs = [(r.get(field), _rerun(r, field)) for r in rows]
    scored = [(s, g) for s, g in pairs if s is not None]
    rerun_scored = [(s, g) for s, g in scored if g is not None]
    return Horizon(
        name=name,
        stored_hits=sum(1 for s, _ in scored if s),
        stored_n=len(scored),
        rerun_hits=sum(1 for _, g in rerun_scored if g),
        rerun_n=len(rerun_scored),
        tolerance=tolerance,
    )


def compare(
    rows, days: int = 180, settle_days: int = 7, tolerance: float = 2.0
) -> Report:
    """Re-score a closed window against its stored record; writes nothing."""
    rows = [dict(r) for r in rows]
    verdicts: dict[str, int] = {}
    verdict_mismatches: list[tuple[int, str, str]] = []
    outcome_mismatches: list[tuple[int, str]] = []
    for r in rows:
        stored, event = r.get("verdict"), r.get("event_verdict")
        verdicts[stored] = verdicts.get(stored, 0) + 1
        if stored != event:
            verdict_mismatches.append((r["id"], stored, event))
        for field in FIELDS:
            if _rerun(r, field) != r.get(field):
                outcome_mismatches.append((r["id"], field))
    return Report(
        window_days=days,
        settle_days=settle_days,
        rows=len(rows),
        verdicts=verdicts,
        horizons=tuple(_horizon(n, rows, f, tolerance) for n, f in HORIZONS),
        verdict_mismatches=verdict_mismatches,
        outcome_mismatches=outcome_mismatches,
        tolerance=tolerance,
    )


async def load(pool, days: int, settle_days: int) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT a.id, a.event_id, a.verdict, e.verdict AS event_verdict, e.timestamp,
               a.price_move_pct, a.correct, a.ex2, a.ex4, a.correct2, a.correct4
        FROM accuracy_outcomes a JOIN events e ON e.id = a.event_id
        WHERE e.timestamp >= now() - ($1 || ' days')::interval
          AND e.timestamp < now() - ($2 || ' days')::interval
        ORDER BY e.timestamp, a.id
        """,
        str(days),
        str(settle_days),
    )
    return [dict(r) for r in rows]


async def _run(args) -> int:
    from server import db

    pool = await db.connect(args.dsn, min_size=1, max_size=2)
    try:
        rows = await load(pool, args.days, args.settle_days)
        if not rows:
            print("no closed outcomes in the window: nothing to verify")
            return 2
        report = compare(rows, args.days, args.settle_days, args.tolerance)
        print(report.render())
        return 0 if report.ok else 1
    finally:
        await db.disconnect()


def main(argv=None) -> int:
    from server.settings import get_settings

    ap = argparse.ArgumentParser(
        description="Verify a closed outcome window, read-only."
    )
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--settle-days", type=int, default=7)
    ap.add_argument("--tolerance", type=float, default=2.0, help="percentage points")
    ap.add_argument(
        "--dsn",
        default=os.getenv("WORLDFIN_DATABASE_URL") or get_settings().database_url,
    )
    return asyncio.run(_run(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
