# Stack and supported floors

What this repository actually runs on, and the oldest version each piece is tested
against. "Floor" means the lowest version CI proves; anything newer is expected but not
proven. Update this file in the same PR that moves a pin (`tests/test_stack_doc.py` fails
when a pin and this table disagree).

| Layer | Runs today | Floor | Why the floor | Where it is pinned |
|---|---|---|---|---|
| Python | **3.14.8** (local and CI) | **3.14** | PEP 649 deferred annotations and `except*` are used; the vendored engine's `lxml` floor is 3.14-ready | `pyproject.toml` `requires-python`, `.github/actions/setup-python` |
| Free-threaded Python | 3.14t, side job only | — | Not adopted: see "Free-threaded evaluation" in `docs/PERF.md` | `.github/workflows/free-threaded.yml` |
| Postgres | **18** | **18** | `gen_random_uuid()` defaults, `MERGE`-free `ON CONFLICT ... RETURNING (xmax = 0)` on 18; the integration suite runs on it | `docker-compose.yml`, `.github/workflows/ci.yml` service, `server/migrations` |
| Node (web) | **26.8.1** | **22.18** | Vite+ 1.1.0 (`vite-plus`) declares `^22.18.0 \|\| ^24.11.0 \|\| >=26` in its own metadata; CI and the image use 26 | `web/package.json`, `web/Dockerfile`, `.github/workflows/ci.yml` |
| Vite+ (`vp`) | **1.1.0** | 1.1.0 | the `vite` specifier is aliased to `@voidzero-dev/vite-plus-core@1.1.0`; the toolchain (dev/build/check/test) is one binary | `web/package.json` |
| TypeScript | **7.0.2** | 7.0 | `vp check` runs the TS 7 checker; TS 6 cannot parse the `satisfies` + const-type-parameter use in `web/src` | `web/package.json` |
| FastAPI | **0.143** | 0.143 | `app.routes` wraps included routers; the auth-surface test depends on the 0.14x route objects | `pyproject.toml` `server` group |
| pandas / yfinance | **3.0.6 / 1.7.0** | same | Copy-on-Write is mandatory in pandas 3; the scoring code relies on it | `pyproject.toml` with compatibility ceilings (`<4`, `<2`) |
| spaCy | **3.8.16** | 3.8 | `en_core_web_sm` 3.8.0 model, loaded once per process | `pyproject.toml`, `[tool.uv.sources]` |
| Laya | 0.4.6 (optional group) | 0.4.6 | sector/direction classifier; absent on Linux ARM CI, in which case the keyword layer answers | `pyproject.toml` `laya` extra |
| lxml | **6.1.3** | 6.0.2 | stable only: the 7.0 beta was on the extraction path and was removed (plan M2.4) | `pyproject.toml` |
| Redis | optional | 8 | only needed when `WEB_CONCURRENCY > 1`; startup refuses that combination without it | `server/rate_limit.py`, `docs/SECURITY.md` |
| Docker images | `python:3.14-slim`, `node:26-slim`, `nginx:1.31-alpine` | — | pinned by digest in all three Dockerfiles | `tests/test_supply_chain.py` |

## What is deliberately old

- **No Redis in production.** One API replica; the rate limiter is in-process unless
  `WORLDFIN_REDIS_URL` is set. Scaling is a documented, gated step, not an accident
  (`docs/RUNBOOK.md`, plan M6.3).
- **No queue.** Ingest is a GitHub Action dispatched by the Cloudflare cron Worker; there
  is exactly one scheduler (`docs/DEPLOY.md`).
- **No frontend framework.** The SPA is plain TypeScript with a small store and panel
  layout; the only heavy runtime dependency is `globe.gl`, which is a lazy chunk.

## How the floors are enforced

- `make stack-check` — parses this table and the pins above; fails on drift
  (`tests/test_stack_doc.py`).
- `make server-group-check` — installs only the `server` dependency group into a scratch
  environment and imports the API and worker. Proves one dependency source rather than
  "it works because everything is installed".
- `.github/workflows/free-threaded.yml` — manual job that asserts the 3.14t build imports
  its native extensions with the GIL disabled.
