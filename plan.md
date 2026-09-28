# fin-scrape — audit follow-ups

What remains from the hardening audit of the WorldFin API. The defects it found (rate
limiter keyed on a client-written header, non-constant-time key comparison, unlimited
half-open probes, an unbounded response cache, two red CI gates, ETag lists and `*`)
are fixed and recorded in `notes.md`.

## Still open

- **The default API key and CORS `*` are warned about locally, refused in production.**
  Under `WORLDFIN_ENV=production` the API will not start while `FINSCRAPE_API_KEY` is
  the value published in this repository or `WORLDFIN_CORS_ORIGINS` is unset or `*`.
- **The rate limiter and response cache live in process memory.** Both are bounded, and
  both carry a `ponytail:` comment naming the ceiling. On more than one replica, or on
  serverless functions that start cold, each instance keeps its own counts and cache;
  the upgrade path is Redis (a sorted set for the limiter, `GET`/`SETEX` for the cache).
- **`is_public_ip` treats documentation ranges such as `203.0.113.0/24` as private.**
  Harmless, because no real peer uses them.
- **The vendored `finscrape/` tree has its own ruff debt.** It sits outside `NEW_DIRS`
  by design and was left alone.
