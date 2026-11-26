# 0004 Supabase

## Status

Accepted, 2026-11-26.

## Context

The project needs a managed Postgres it can reach from a container without operating a database host, and it needs the free tier to be safe rather than a trap that silently pauses the service or runs out of disk.

## Decision

Use Supabase Postgres as the database, in the Seoul region, reached through the session pooler on port 5432. Row level security is on for every table, so the Data API exposes nothing. The API itself is a Render Docker service built from [Dockerfile.api](../../Dockerfile.api), which connects to Postgres directly rather than through the Data API.

Schema changes live in `server/migrations/` and are applied by setting `WORLDFIN_RUN_MIGRATIONS=true`, so a deploy controls its own migrations instead of depending on a manual step.

The free tier is 500 MB of database, and it pauses after 7 days of low activity. [COST.md](../COST.md) records both, plus the two guards that keep the project under the limit: the worker evicts to `WORLDFIN_DB_MAX_MB` 400 MB, and [check_prod.py](../../scripts/check_prod.py) alerts above 450 MB. The first paid step, if it is needed, is Supabase Pro from $25 per month with 8 GB.

## Consequences

The database is managed, reachable over a pooled connection, and costs nothing at current volume. The ceiling is real: 500 MB is a hard wall, and the project relies on retention and eviction to stay below it, with an alert as the early warning rather than a guarantee.

RLS on every table means an accidentally exposed anon key still returns nothing, which is the property the exposed Data API needs. It also means every direct query path must respect the policies, and the API is the intended path.

Revisit this decision when the event table approaches the 500 MB wall despite retention and eviction, or when a pause after low activity is unacceptable for a period the project cannot tolerate. At that point Supabase Pro is the documented next step.

## Evidence

- [DEPLOY.md](../DEPLOY.md): Seoul, session pooler port 5432, RLS on every table, Render Docker service.
- [Dockerfile.api](../../Dockerfile.api): the API image deployed on Render.
- [COST.md](../COST.md): 500 MB free tier, 7-day pause, 400 MB eviction, 450 MB alert, Pro from $25 with 8 GB.
- [check_prod.py](../../scripts/check_prod.py): production size alert.
- [server/migrations](../../server/migrations): migration files applied by `WORLDFIN_RUN_MIGRATIONS=true`.
