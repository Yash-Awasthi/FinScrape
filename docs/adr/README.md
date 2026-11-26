# Architecture decision records

This directory records the decisions that shape FinScrape, in the order they were made. Each record states the context, the decision, its consequences and the evidence behind it. Records are historical: they are not rewritten to match later changes, and a new record supersedes an old one when a decision is revisited.

## Index

- [0001 No Redis yet](0001-no-redis-yet.md) - Accepted - Rate limiting, caching and WebSocket fan-out stay in-process on one API replica until load demands a shared store.
- [0002 Free models](0002-free-models.md) - Accepted - Production analysis runs on TokenHarbor free models with a heuristic fallback, behind an evaluation gate.
- [0003 Static SPA](0003-static-spa.md) - Accepted - The web app is a static Vite SPA on Cloudflare Pages that talks to the API over HTTPS.
- [0004 Supabase](0004-supabase.md) - Accepted - Supabase Postgres hosts the database, with RLS on every table and retention keeping it inside the free tier.
- [0005 Single scheduler](0005-single-scheduler.md) - Accepted - One Cloudflare cron Worker dispatches every timed workflow; GitHub schedules are unused.
- [0006 WebSocket fan-out](0006-ws-fanout.md) - Accepted - Redis pub/sub on one fixed topic is the cross-process WebSocket path; in-process broadcast stays the single-replica default and Durable Objects are rejected.

## How to add an ADR

Take the next number, copy the five sections, add the index line here, and keep links relative to this directory. A new record starts with status Proposed and becomes Accepted when the decision is taken.

The five sections, in order, are Status, Context, Decision, Consequences and Evidence.

## Related documents

- [ARCHITECTURE.md](../ARCHITECTURE.md)
- [DEPLOY.md](../DEPLOY.md)
- [STACK.md](../STACK.md)
- [RUNBOOK.md](../RUNBOOK.md)
- [COST.md](../COST.md)
