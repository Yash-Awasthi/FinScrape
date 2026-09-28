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

Facts about the owner's setup that the items below rely on (as of 28 Sep 2026):

- **Deployment target:** free services, with the SPA on Vercel and Postgres on Supabase.
  The API and worker host is still open (item 9).
- **GPU:** an RTX 4060 (8 GB) on the local machine; long training runs are fine (item 11).
- **Accounts still to create, when item 9 starts:** Vercel, Supabase, a hosted LLM key
  (OpenRouter or similar, since Ollama is not available on free hosting), and possibly a
  free always-on host for the API and worker. Claude says which ones once the options
  are compared.
- **ReliefWeb:** app name requested on 28 Sep 2026 with the owner's NIT Raipur address
  (G1). When it arrives, the owner adds `RELIEFWEB_APPNAME` to `.env`.
- **Store:** stick to one data store, chosen on how each path is used (item 10).
- Ask the owner only for real decisions or credentials, not for anything in the repo.

## Open

### 9. Deploy: finish the Supabase move
Found live since June: Cloudflare Pages (SPA, `winfin.pages.dev`), Render API
(`winfin-api`), GitHub Actions ingest, Neon Postgres. Vercel is not needed. On 29 Sep
Neon's data (9,690 events, 837 outcomes) was copied into Supabase (schema 0001–0007,
RLS on); Render and the `WORLDFIN_DATABASE_URL` secret point at Supabase; Render runs
`WORLDFIN_ENV=production` with CORS `https://winfin.pages.dev`. PR #6 merged; the
live API serves 9,698 events from Supabase and the first ingest run inserted 8
(GDELT 6 with no 429s).
- The freemodel.dev LLM key expired 28 Jul, so ingest has run on the heuristic
  fallback since (6,634 CAUTIOUS). Get a working key (OpenRouter free or paid) into
  the GitHub secret and Render env.
- Parenthesised acronyms still read as tickers ("Rapid Support Forces (RSF)", "(OCHA)"
  on event 21206). Keep a `(TICK)` match only when it is a listed symbol.
- The dashboard on Pages is an older build; redeploy with the `wrangler` command in
  `docs/DEPLOY.md` once `npx wrangler login` has been run on this machine.
- The 837 outcomes were scored with the old same-day window; re-score them with
  `server.accuracy.backtest` (lookback 180 days) against Supabase.
- Rotate the Supabase password and Render key that were pasted into a chat.
- Once Supabase has run a week cleanly, delete the Neon project.
- Email digest: add a scheduled Action for `python -m worker.digest daily` once the
  owner sets `RESEND_PROXY_URL` and `FINSCRAPE_DIGEST_TO`.

### 11. Laya: stage 1 and the daily loop (parked by the owner, 29 Sep)
The current promoted checkpoint stays in use; the 03:30 task keeps running unattended.
Built (7fb3bcba): `scripts/laya_train/` has `train.py` (LoRA or full),
`build_pretrain.py` (FNSPID and two Twitter finance sets) and `daily.py` (Claude
labels the headlines Laya is unsure of via `claude -p`, a LoRA candidate trains, and
it is promoted only if it beats the current model on gold + holdout). The Windows
task "WorldFin Laya daily" runs it at 03:30; state, logs and `history.jsonl` live in
`C:\Users\yasha\laya-ft`.
- First run (28 Sep): 494 hand labels plus 58 from Claude; stock 71.4% vs candidate
  72.9% on 70 gold + holdout cases, promoted, and `.env` now sets
  `FINSCRAPE_LAYA_MODEL`. That was a one-case gain, so promotion now needs at least
  2 more correct cases (`MIN_GAIN`).
- The owner runs stage 1 from `Desktop\laya-stage1.txt` and reports the
  `STOCK x% STAGE1 y%` line. Record it; if stage 1 loses, delete `laya-ft\stage1`
  so the daily LoRA starts from the stock model again.
- Read `history.jsonl` and the latest `logs\daily-*.log`: did runs happen, did
  labels arrive, were promotions real gains. Spot-check Claude's labels.
- A promoted model loads only in new processes. Make `finscrape.analysis.laya`
  reload when `current\` changes, or restart the API and worker on promotion.
- Grow the gold set towards 250 and have the owner review it, then drop its
  provisional mark; at 56 cases a one-headline gap is 1.8 points.
- Direction has no gold at all; label a direction set and measure it.

## Gated

### G1. ReliefWeb source
v1 is retired (410) and v2 rejects unapproved app names (403). Needs the owner to
request an app name at https://apidoc.reliefweb.int/parameters#appname and set
`RELIEFWEB_APPNAME` in `.env`; the source turns itself on after that.
Checked 28 Sep 2026: `.env` has no `RELIEFWEB_APPNAME`, and the worker built no reliefweb source.
Requested 28 Sep 2026 with the owner's NIT Raipur address; waiting on ReliefWeb's reply.

G2–G5 were decided by the owner on 28 Sep 2026 and became items 9–11.
