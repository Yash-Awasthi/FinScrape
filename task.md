# Tasks

The working list for WorldFin. `notes.md` is the handover log that goes with it.

## How to work this list

- Take open items top to bottom. For each one: investigate, write a failing test,
  fix, check it live against the running stack, then make one commit.
- When an item closes, delete it here and add one line to `notes.md` under
  "Closed" (what changed, the commit, the live check).
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
- **Keys:** `.env` holds `RENDER_API_KEY` and `OPENROUTER_API_KEY`; `RENDER_API_KEY` is also a
  Windows user variable. Ask the owner only for real decisions or credentials.
- **Store:** one data store, Postgres.

## Open

### 9. Production: what is left
- Owner: rotate the Supabase password, the TokenHarbor, OpenRouter and Render keys, and the
  fine-grained GitHub PAT, all pasted into a chat. Then update GitHub secrets, the Render
  env (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANALYZE_DISPATCH_TOKEN`) and the cron
  Worker (`npx wrangler secret put GH_TOKEN` in `ops/ingest-cron`).
- Owner: delete the Neon project after 6 Oct (a clean week on Supabase); then drop the
  remaining Neon mentions in `ingest.yml`, `worker/main.py` and the docs.
- Owner: the email digest needs `RESEND_PROXY_URL` and `FINSCRAPE_DIGEST_TO`; then add a
  scheduled Action for `python -m worker.digest daily`, or drop the digest.
- Owner: mark the local-only compose password (`worldfin`, Postgres on 127.0.0.1) a false
  positive in GitGuardian.
- TokenHarbor refuses requests from Render (403 `request_forbidden`) and serves GitHub
  runners. So the API runs AI analysis only on click with OpenRouter free models
  (`FINSCRAPE_MODEL`, `FINSCRAPE_MODEL_FALLBACK` on Render), and when all of them fail it
  dispatches the `analyze` workflow, at most `ANALYZE_DISPATCH_PER_HOUR` (20) times an hour.
  Ingest keeps TokenHarbor (deepseek, then mimo).
- `world/times_of_israel` fails from GitHub runners (blocked there, fine locally).
- About 4,600 heuristic-era rows were left unanalysed on purpose: re-running them costs
  about 4.5 hours of the shared LLM key for roughly 600 useful rows, and scenarios and
  the backtest already skip them.

### 11. Sector model and call tuning
Follow `docs/LAYA_PLAN.md`; the next step is steps 1 and 2 (S&P 500 universe and prices,
then the September 2026 GDELT pilot against the 1,000 single-company events per month gate).
The nightly LoRA loop is stopped (`WorldFin Laya daily` is disabled) and production stays
on `laya-20261001-1041`. The loop's runs and measurements are in this file's git history
before the plan landed (27a668c8).

Live track record on 2 Oct: 58.5% of 342 scored calls; PULL_OUT 59.7% (305), INVEST
48.6% (37).
