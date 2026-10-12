# Better Stack: fin-scrape (WorldFin)

Upgrade plan built from the code itself (`pyproject.toml`, `uv.lock`, both Dockerfiles, compose files, CI and the import graph of `finscrape/`, `server/`, `worker/` and `web/src`). Target versions were read from PyPI, npm, Docker Hub and GitHub releases on 2026-10-12. "Newest" includes alpha/beta/RC builds; "Stable" is the newest final release.

This repo is already ahead of the others (actions v7, uv, Vite+, Vitest 5). The gains here are consistency and the infrastructure images, not a rewrite.

## What the code actually uses

- `finscrape/` (~22k lines, excluding `absorbed/`): vendored Scrapling engine (patchright, curl_cffi, lxml, cssselect, orjson, msgspec), RSS + trafilatura extraction, yfinance market data (pulls in pandas), lazy spaCy NLP and an optional `laya` classifier.
- HTTP in the core is split: `requests` in 21 files, `curl_cffi` in 8. Threads (`threading`, `concurrent.futures`) drive the scrapers.
- `server/` (~4k lines): FastAPI + asyncpg with raw SQL migrations, optional Redis pub/sub (`server/pubsub.py`, lazy import), Prometheus metrics, WebSocket fan-out (`ws.py`), an OpenAI-compatible LLM client in `ai.py` with model fallback.
- `worker/` (~1k lines): APScheduler 3 `AsyncIOScheduler`.
- `web/` (~3.9k lines of TS): globe.gl on Vite+ (`vp`), Vitest 5, Playwright; served by nginx.
- CI installs Python 3.13 through `astral-sh/setup-uv`; both Docker images are `python:3.13-slim` and install with **pip**, not from `uv.lock`.

## Consistency fixes first

| Problem | Evidence | Fix |
|---|---|---|
| Two dependency lists | `requirements.txt` duplicates `pyproject.toml` and has already drifted (no spaCy, trafilatura or scipy) | Delete `requirements.txt`; build images from `uv.lock` |
| Images ignore the lockfile | `Dockerfile.api` pip-installs loose `>=` specs; `Dockerfile.worker` installs `requirements.txt` plus extra loose specs | `COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/` then `uv sync --frozen --no-dev --group server` in both images. Same versions in CI and prod |
| `requires-python = ">=3.11"`, pyright `pythonVersion = "3.11"` | CI and images only run 3.13 | Raise both to the version actually shipped |
| Floors far behind the lock | e.g. `fastapi>=0.110`, `lxml>=5.0.0`, `patchright>=1.0.0` | Raise floors to the versions in `uv.lock` so a fresh resolve cannot go backwards |
| Undeclared direct import | `pandas` is imported in `market_data.py`, `accuracy.py`, `server/routes/market.py`, but only arrives through yfinance | Declare `pandas` explicitly |

## Python runtime and tooling

| Item | Current | Stable | Newest | Pick |
|---|---|---|---|---|
| Python | 3.13 | 3.14.8 | 3.15.0rc3 | **3.14.8** now; 3.15.0 when it goes final (RC3 is out) |
| uv | lock + setup-uv v10.2.0 | 0.13.0 / setup-uv v10.3.0 | same | **0.13.0**, pin `version:` in the composite action |
| ruff | 0.16.9 | 0.17.0 | 0.17.0 | **0.17.0** (keep the exact pin, review new rules) |
| Type checker | pyright 1.1.411 | pyright 1.1.414 | ty 0.0.86 | **pyright 1.1.414**, plus **ty** as a non-blocking CI job |
| pytest | >=9.0.3 | 9.1.1 | 9.1.1 | **9.1.1** |
| httpx2 (test client) | >=2.13 | 2.13.1 | 2.13.1 | keep |

Python 3.14 is a straight win for this code: faster startup and the new incremental GC help the long-running worker. The free-threaded build (`3.14t`) is tempting because the scrapers are thread-based. Benchmark it in a side job first: lxml, curl_cffi and orjson all need free-threaded wheels, and any missing one silently re-enables the GIL.

## Python libraries

| Package | Lock floor today | Stable | Newest | Pick |
|---|---|---|---|---|
| fastapi | >=0.110 | 0.143.0 | 0.143.0 | **0.143.0** |
| uvicorn[standard] | >=0.29 | 0.54.0 | 0.54.0 | **0.54.0**, or Granian 2.8.4 (see below) |
| pydantic / pydantic-settings | >=2.6 / >=2.2 | 2.14.1 / 2.15.0 | same | **2.14.1 / 2.15.0** |
| asyncpg | >=0.29 | 0.32.0 | 0.32.0 | **0.32.0** |
| redis (py) | >=5.0 | 8.1.0 | 8.1.0 | **8.1.0** |
| prometheus-client | >=0.20 | 0.26.0 | 0.26.0 | **0.26.0** |
| apscheduler | >=3.10 | 3.11.3 | 4.0.0a6 | **3.11.3** (4.0 is still alpha and a full API rewrite; revisit at beta) |
| lxml | >=5.0.0 | 6.1.3 | 7.0.0b1 | **7.0.0b1** behind the test suite, fallback 6.1.3 |
| curl-cffi | >=0.7.0 | 0.16.3 | 0.16.3 | **0.16.3** |
| orjson | >=3.9.0 | 3.13.0 | 3.13.0 | **3.13.0** |
| msgspec | >=0.18.0 | 0.22.0 | 0.22.0 | **0.22.0** |
| patchright | >=1.0.0 | 1.63.0 | 1.63.0 | **1.63.0** |
| browserforge | >=1.1.0 | 1.2.4 | 1.2.4 | **1.2.4** |
| yfinance | >=0.2.30 | 1.7.0 | 1.7.0 | **1.7.0** |
| spacy | >=3.8.14 | 3.8.16 | 4.0.0.dev3 | **3.8.16** (4.0 dev builds break model compatibility) |
| trafilatura | >=2.2.0 | 2.3.1 | 2.3.1 | **2.3.1** |
| scipy | >=1.17.1 | 1.18.1 | 1.18.1 | **1.18.1** |
| pyarrow (dev) | >=25.0.1 | 26.0.0 | 26.0.0 | **26.0.0** |
| laya (extra) | >=0.3.20 | 0.4.6 | 0.4.6 | **0.4.6** |

Code-level improvements:

- **One HTTP client in the core.** `requests` (21 files) and `curl_cffi` (8 files) overlap. `curl_cffi.requests` is API-compatible with `requests`, adds browser TLS fingerprints and has an async session. Moving the 21 files over drops `requests` and gives every scraper the same impersonation and retry behaviour.
- **Granian instead of uvicorn** for the API container: a Rust HTTP server with native ASGI and WebSocket support, lower tail latency and lower memory. Uvicorn stays fine for `make` dev runs.
- **Redis 8 / Valkey 9** for the optional pub/sub. The client code (`redis.asyncio`) is unchanged for either.

## Infrastructure images

| Image | Current | Latest | Pick |
|---|---|---|---|
| `python` (both Dockerfiles) | 3.13-slim | 3.14.8-slim | **3.14-slim** |
| `postgres` | 16.4-alpine | 18.6-alpine (19beta4) | **18-alpine**. Needs `pg_upgrade` or the existing `make backup` / `make restore` round-trip; volumes are not compatible across majors |
| `redis` | 7.2.5-alpine | 8.10.2-alpine | **8.10-alpine**, or `valkey/valkey:9.1-alpine` for a BSD-licensed drop-in |
| `prom/prometheus` | v2.54.1 | v3.15.0 | **v3.15.0** (check `obs/` config against 3.x removals) |
| `grafana/loki` | 3.1.1 | 3.7.8 | **3.7.8** |
| `grafana/promtail` | 3.1.1 | end-of-life | **Replace with Grafana Alloy v1.20.1** |
| `grafana/grafana` | 11.2.0 | 13.2.3 | **13.2.3** |
| `node` (web build) | 22-slim | 26 | **26-slim**, matching CI |
| `nginx` (web) | 1.27-alpine | 1.31.6-alpine (mainline) / 1.30.5 (stable) | **1.31-alpine** |

Postgres 18 also brings async I/O and faster `VACUUM`, which matter for the ingest tables cleaned up by `0003_storage_hygiene.sql`.

## Web (`web/package.json`)

| Package | Current | Latest | Pick |
|---|---|---|---|
| `vite-plus` / `@voidzero-dev/vite-plus-core` | 1.1.0 | 1.1.0 | keep |
| `vitest` | 5.0.3 | 5.0.4 | **5.0.4** (update the override too) |
| `typescript` | ^5.6.0 | 7.0.2 | **7.0.2** |
| `globe.gl` | ^2.34.0 | 2.46.2 | **2.46.2** |
| `jsdom` | ^25.0.0 | 30.1.2 | **30.1.2** |
| `@playwright/test` | ^1.48.0 | 1.64.0 | **1.64.0** |
| `@types/node` | ^24.19.2 | 26.6.5 | **26.6.5** |

The web app is ~3.9k lines of framework-free TS built around globe.gl. No framework change is recommended; the panels are imperative DOM code that a framework would not simplify much.

## CI

| Action | Current | Latest |
|---|---|---|
| `astral-sh/setup-uv` | v10.2.0 | v10.3.0 |
| `actions/cache` | v4 | v6.1.0 |
| `actions/setup-node` | v7, Node 24 | v7, **Node 26** |
| `aquasecurity/trivy-action` | v0.36.0 | v0.36.0 (current) |

## Order of work

1. Delete `requirements.txt`, rebuild both images from `uv.lock`, declare `pandas`, raise floors.
2. Python 3.14 in CI, Dockerfiles, `requires-python` and pyright.
3. Library bumps in one `uv lock --upgrade` pass; run `make ci`.
4. Web bumps and TypeScript 7.
5. Observability: Prometheus 3, Loki 3.7, Grafana 13, Promtail → Alloy.
6. Postgres 18 via `make backup` → new volume → `make restore`, then Redis 8 / Valkey 9.
7. `requests` → `curl_cffi` consolidation, Granian for the API image.
8. Python 3.15 once final; free-threaded benchmark as a side job.

`make ci` must stay green after each step.
