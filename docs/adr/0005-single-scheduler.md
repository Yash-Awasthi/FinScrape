# 0005 Single scheduler

## Status

Accepted, 2026-11-26.

## Context

Timed work includes ingest, summaries, backups and weekly scoring. Each needs to fire on a clock, and more than one clock is more than one place for the same job to run twice or not at all. A single dispatch point is easier to reason about than several that must agree.

## Decision

Use one Cloudflare cron Worker as the only scheduler for timed workflows. [wrangler.jsonc](../../ops/ingest-cron/wrangler.jsonc) defines Worker `winfin-ingest-cron` with cron `*/10 * * * *` and `INGEST_EVERY_HOURS=24`; its comment states that it is the only scheduler for timed workflows.

[DEPLOY.md](../DEPLOY.md) records the dispatch pattern: the Worker dispatches ingest, summary, backup and score-week at :13 and :43 past the hour. GitHub's built-in schedule trigger is a fallback only, because it fires every 3 to 6 hours and is disabled after 60 days without commits; no workflow carries a schedule block. For short demos, `make ingest-every HOURS=1` from the [Makefile](../../Makefile) runs hourly.

## Consequences

There is exactly one place to look when a timed job does not run, and no risk of two schedulers racing on the same workflow. The trade is a single point of failure: an outage of the Worker delays every timed job, with no independent scheduler to take over.

GitHub schedules are deliberately unused, so the repository does not accumulate disabled or drifting cron entries. The fallback exists as a documented option but is not wired into any workflow.

The ten-minute cron also sets the floor on scheduling granularity: nothing timed can be more frequent than the Worker's tick, apart from a manual command.

Revisit this decision when a job needs finer granularity than the cron tick, or when the project genuinely needs a second independent scheduler for redundancy. Adding one before then would reintroduce the coordination problem this decision avoids.

## Evidence

- [wrangler.jsonc](../../ops/ingest-cron/wrangler.jsonc): Worker `winfin-ingest-cron`, cron `*/10 * * * *`, `INGEST_EVERY_HOURS=24`, single-scheduler comment.
- [DEPLOY.md](../DEPLOY.md): dispatch at :13 and :43, GitHub schedule fallback every 3 to 6 hours, disabled after 60 days.
- [Makefile](../../Makefile): `make ingest-every HOURS=1` for hourly demos.
