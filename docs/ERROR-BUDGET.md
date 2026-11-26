# FinScrape - error budget policy

The SLO targets live in `docs/SLO.md`; this page says what a spent budget does to the
work. An error budget is the failure a target already allows, so spending it is a schedule
decision, not an outage, and the policy turns a missed promise into ordered changes.

## The budgets

| Signal | Target | Budget | Measured from |
|---|---|---|---|
| Availability | 99.5% per calendar month | 3 h 39 m in an average 730 h month (3 h 43 m 12 s in a 31-day month; 3 h 36 m in a 30-day month) | share of HTTP requests that do not fail |
| `/api/events` p95 | 400 ms | the share of requests answered within 400 ms; at most 5% may exceed 400 ms | `worldfin_http_request_seconds`, `path="/api/events"` |
| Ingest cycle | finishes within 2x its interval | every cycle later than 2x counts as one miss, against the 0.5% allowance | `scrape_runs.started_at` and `finished_at` |
| Dashboard LCP | 2.5 s | the share of page loads at or under 2.5 s; `needs-verify` until measured | Lighthouse, then a field reading |

The availability budget is 0.5 percent of a month: 0.005 x 730 h = 3.65 h, or 3 h 39 m.
The table carries each month length to the second, so a 30-day month has a smaller budget;
availability counts requests, not minutes.

## Burn-rate triggers

Burn rate is budget spent per hour, relative to the rate that exhausts the month: 1.0
spends the whole budget in one month, 14.6 in about two days.

| Stage | Window | Budget spent | Burn rate | Response |
|---|---|---|---|---|
| Fast burn | 1 hour | 2% | 14.6x | page now, day or night |
| Slow burn | 6 hours | 10% | 12.2x | open an incident |
| Spent | 3 days | 25% | 2.5x | reliability ticket, no page |

- 2 percent in 1 hour: 0.02 / (1 / 730) = 14.6x.
- 10 percent in 6 hours: 0.10 / (6 / 730) = 12.2x.
- 25 percent in 3 days: 0.25 / (72 / 730) = 2.5x.

In seconds of the availability budget, 2 percent is 4 m 23 s, 10 percent is 21 m 55 s and
25 percent is 54 m 47 s. One hour at 14.6x spends what 14.6 quiet hours spend.

The triggers run on the SLO query, so a fast burn that clears before anyone looks is still
an incident, and the 3-day ticket catches the slow leak that never pages.

## The freeze ladder

Stages are entered and left in order; only the owner lowers one, in the incident issue.

1. **Stage 1 - feature work pauses.** Merges that add behavior stop; reliability,
   data-loss and security fixes continue. Entered on an open incident, or when the 3-day
   trigger confirms a quarter of the month's budget is gone.
2. **Stage 2 - only SLO-restoring changes plus security.** New behavior is out, including
   refactors that do not restore the target. Entered on the fast-burn trigger, or at half
   the month's budget.
3. **Stage 3 - release freeze except rollback and incident fixes.** Deploys stop except a
   rollback, a change that restores the target, or a fix for the incident at hand. Entered
   when the budget is spent or the target is missed.

What does not freeze, at any stage: security patches, backups and restore drills,
data-loss fixes, incident response, and the ability to roll back. These reduce expected
loss; freezing them would protect a number by raising the risk behind it. A patch shipped
during a freeze still passes its normal review and tests.

Freezing is not a penalty; the ladder holds until the measured recovery below.

## Spending the budget on purpose

A migration, provider switch or load test that can fail requests is declared first, with:

- the expected spend, as a percentage of the month's budget and the window it lands in;
- the signal it will spend from, and the measurement that will confirm it;
- the owner's sign-off, recorded with the change.

A declared spend that runs over its estimate is an incident at the rate it produced; an
undeclared change is a process failure even when the month ends above target.

An incident that spends the last quarter of a month's budget freezes the next planned
change, whatever the stage, until recovery; the change moves to a later month.

## Recovery and unfreeze

A budget is restored, not asserted. A stage is lowered only when measured availability has
been at or above target for 7 consecutive days, and this review is written. The owner signs
off every unfreeze; the review records:

- the window and burn rate that opened the incident, and the budget spent;
- the signal that failed, with the query and the numbers that showed it;
- the fix and the change that would have caught it earlier;
- the remaining budget and the stage the ladder returns to.

The 7 days run on the SLO measurement, not a quieter dashboard; one good day clears nothing.

## Escalation

| Stage | Who decides | Where it is recorded |
|---|---|---|
| fast burn page | the on-call engineer acknowledges and starts the incident | the incident issue, opened from the alert |
| slow burn incident | the on-call engineer opens it; the owner is notified | the incident issue, with the 6-hour window quoted |
| stage 1 | the on-call engineer | the incident issue, tagged with the stage |
| stage 2 | the owner, on the on-call engineer's report | the incident issue, with the spend so far |
| stage 3 | the owner | the incident issue and the release checklist |
| unfreeze | the owner | the review note, linked from the incident issue |

A decision that is not in the issue did not happen; roles change, the record does not.

## Measurement

Everything above reads a source that already exists in this tree:

- `worldfin_http_requests_total` (labels `method`, `path`, `status`) counts requests; the
  availability budget is the failing share of this counter.
- `worldfin_http_request_seconds` is the latency histogram behind the 400 ms target;
  filter `path="/api/events"` for the route's own budget. Both are the HTTP rows of
  `docs/RUNBOOK.md` section 2.
- `scrape_runs` holds one row per ingest cycle with `started_at`, `finished_at`, `status`
  and `events_ingested`; the 2x interval check is the difference between the two times.
- `scripts/check_prod.py` is the existing alert for no event in 3 hours and for database
  size, and it fails the run rather than warning.
- `scripts/warm.py` measures cold start against the 50 s the DEPLOY page quotes; a cold
  start paid by a real user is availability and latency budget at once.
- Lighthouse measures the dashboard LCP against 2.5 s. No production LCP reading exists in
  the repo yet, so that row stays `needs-verify` until one is taken and recorded.

No stage is entered or left on a number that cannot be reproduced from these sources.
