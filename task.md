# Tasks

The working list for WorldFin. `notes.md` records what is known about it.

## How to work this list

- Take open items top to bottom. For each one: investigate, write a failing test,
  fix, check it live against the running stack, then make one commit.
- When an item closes, delete it here; the commit message records what changed and the
  live check. Facts worth keeping go to `notes.md`.
- A **gated** item needs something only the owner can supply. Skip it and add a
  line under its entry saying what was checked and why it is still blocked.
- Push at the end of the session.

Local stack: API `:8010`, Postgres 17 `:5434` (database `worldfin`; tests use
`worldfin_test` through `WORLDFIN_TEST_DATABASE_URL`), Ollama `:11434`. The Docker
stack called nexus owns 8000, 5432, 6379, 3000 and 4173; never use those ports.

Start the stack before any live check (each in its own background shell), then
confirm `curl localhost:8010/health` shows `"db":true,"llm":true`:

```
ollama serve                                         # skip if :11434 already answers
.venv/Scripts/python -m server.main                  # API on :8010
.venv/Scripts/python -m worker.main --once           # one ingest cycle, then exits
cd web && npm run dev                                # dashboard on :8080, only if needed
```

Postgres is a Windows service (`postgresql-x64-17`) and is normally already up.
Memory is tight on this machine: Ollama plus Laya plus the API can exhaust it, and
idle background shells may be stopped. Start only what the current item needs,
stop it when the live check is done, and set `FINSCRAPE_LAYA=0` for checks that do
not involve sector labels.

Gates to keep green: `pytest -q`, `ruff check` and `ruff format --check` on the
`NEW_DIRS` in the Makefile, `pyright`, `python -m tests.server.selfcheck`, and in
`web/`: `npm run typecheck`, `npm run test`, `npm run build`, `npx playwright test`.

## Owner context

Facts about the owner's setup that the items below rely on (as of 2 Oct 2026):

- **Deployment:** SPA on Cloudflare Pages (`winfin.pages.dev`), API on Render
  (`winfin-api`), Postgres on Supabase, ingest in the `ingest` Action dispatched by the
  Cloudflare cron Worker `winfin-ingest-cron`.
- **GPU:** an RTX 4060 (8 GB) on the local machine; GPU runs are started by hand only.
- **Keys:** `.env` holds `RENDER_API_KEY`, `OPENROUTER_API_KEY`, `NEON_API_KEY` and the
  TokenHarbor rotation list `OPENAI_API_KEYS` (also a GitHub secret); the Render
  and Neon keys are also Windows user variables. Ask the owner only for real decisions or credentials.
- **Store:** one data store, Postgres.

## Open

Nothing is open.
