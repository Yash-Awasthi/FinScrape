# Contributing to WorldFin

## Setup

```bash
git clone https://github.com/Yash-Awasthi/fin-scrape.git && cd fin-scrape
uv sync -p 3.13 --group server --group dev
cd web && npm ci && cd ..
```

Run the app with `make demo` (Docker) or the no-Docker steps in the [README](README.md).
Database tests need `WORLDFIN_TEST_DATABASE_URL` pointing at a database whose name ends in
`_test`; they truncate tables. [docs/LOCAL-READINESS.md](docs/LOCAL-READINESS.md) shows how
to start a throwaway Postgres for them.

## Layout

| Path | What |
|---|---|
| `finscrape/` | engine: world feeds and ingestors, LLM analysis, Laya sector chain, tickers, scenarios, council, backtest |
| `server/` | FastAPI app, routes, SQL migrations, seed data |
| `worker/` | ingest cycle, sources, correlation, retention |
| `web/` | Vite SPA: landing (`/`) and dashboard (`/app/`) |
| `scripts/` | `llm.py`, `check_prod.py`, `db_backup.py`, `laya_train/` |
| `tests/` | pytest (`tests/server/` needs Postgres) |

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains the data flow.

## Checks

`make ci` runs what CI runs:

| Gate | Command |
|---|---|
| Lint and format (new code, `NEW_DIRS` in the Makefile) | `make lint fmt-check` |
| Types | `make typecheck` |
| Schema self-check | `make selfcheck` |
| Tests | `make test` |
| Web | `cd web && npm run typecheck && npm run test && npm run build && npx playwright test` |
| Real API in a browser | `make e2e-live` (empty `*_test` database on 127.0.0.1) |

The vendored `finscrape/absorbed/` tree and older `finscrape/` modules carry lint debt and
are outside `NEW_DIRS` on purpose.

## Working rules

- A bug fix comes with the test that failed before it.
- Fix a shared function once rather than guarding each caller.
- Comments state only what the code cannot show: an invariant, or why the obvious approach fails.
- Advisory features (scenarios, predictions, sector and ticker impact, the council) are the
  product; do not remove them in a clean-up without asking.

## Commits and pull requests

- One logical change per commit: a subject line in plain prose, then a short body saying why.
- Open pull requests from a branch into `master`; merging to `master` deploys the API.
- CI must be green. The "Workers Builds: fin-scrape" check belongs to another Cloudflare
  account and can be ignored.
