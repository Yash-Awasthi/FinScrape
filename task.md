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

### 9. Production: what is left
Live on Cloudflare Pages (`winfin.pages.dev`), Render (`winfin-api`), Supabase and
the `ingest` Action, dispatched every 30 minutes by the Cloudflare cron Worker
`winfin-ingest-cron` (`ops/ingest-cron`). PRs #6-#11 merged.
- The cron Worker's `GH_TOKEN` secret was set on 29 Sep (fine-grained PAT, this repo,
  Actions read and write); replace it with `npx wrangler secret put GH_TOKEN` in
  `ops/ingest-cron` when it expires or is rotated.
- Ingest watched twice on 29 Sep (runs dispatched by hand): qwen timed out 3 and 8
  times; the second run handed 4 calls to mimo, and 1 of 5 new events fell to the
  heuristic when both failed. GDELT export: 0 429s. Reddit RSS returned the same 100
  posts (spanning 3 days) both times, so sentiment fills slowly. Correlations: 0 so
  far; they need tier-tagged events from several sources in one 24-hour window.
  Re-check once the cron has run for a day.
- Owner: rotate the Supabase password, Render key, TokenHarbor key and the GitHub PAT
  pasted into a chat, and the Nexus Neon password; then update Render env and GitHub secrets.
- Owner: delete the Neon project after a clean week on Supabase (from 29 Sep).
- Owner: put `RENDER_API_KEY` in `.env` (then `make llm MODEL=deepseek-v4.1-flash:free`), or
  set `FINSCRAPE_MODEL` and `FINSCRAPE_MODEL_FALLBACK` on Render by hand; the API still runs mimo first.
- Owner: email digest needs `RESEND_PROXY_URL` and `FINSCRAPE_DIGEST_TO`; then add a
  scheduled Action for `python -m worker.digest daily`.
- GitGuardian flags the local-only compose default password (`worldfin`, Postgres
  bound to 127.0.0.1); mark it a false positive in the dashboard.
- The "Workers Builds: fin-scrape" check fails on every commit, master included; it
  belongs to another Cloudflare account (`bb494...`). Disconnect it or fix it there.
- 30 Sep: qwen3.8-flash:free answered 429 "campaign allowance" on every call, so the
  ingest Action runs mimo first and deepseek as fallback. After the 3000-token fix
  (c200573f) two runs (36689858687, 36691543848) had zero 429s and zero JSON parse
  errors in about 3.5 minutes each; a tolerant parser is not needed for now.
- `world/times_of_israel` fails from GitHub runners (blocked there, fine locally).
- About 4,600 heuristic-era rows were left unanalysed on purpose: re-running them costs
  about 4.5 hours of the shared LLM key for roughly 600 useful rows, and scenarios and
  the backtest already skip them.

### 11. Laya: stage 1 and the daily loop
Claude is the teacher: it writes and reviews the labels; the owner does not review them.
1. Done: the gold set has 243 cases, 187 of them production event subjects from June to
   September 2026, none in train or holdout. Production has few communications and
   real-estate stories (3 and 8 cases).
2. Done, on 243 gold: no Laya 155 (63.8%), stock Laya 155 (63.8%), promoted LoRA 185
   (76.1%). Stock Laya gains energy and financials but pulls 26 `other` stories into a
   sector; the LoRA keeps most `other` right and lifts materials 5/16 to 15/16.
3. Done, twice. First run (30 Sep 16:18 to 1 Oct 03:17, 10.3 h, slowed by VRAM spilling
   into shared memory): kept, 591 of 844 against stock 515. Second run (1 Oct 04:40 to
   09:06) on the rebuilt corpus: 76,488 cases (6,000 company-naming FNSPID headlines per
   sector with direction from wording or the day's move net of SPY, Twitter sets with
   neutrals capped, and the teacher train split), 3 epochs at 20 items/s, best held-out
   loss at epoch 2 (0.292; epoch 3 0.336), no self-distilled direction targets. Scored raw
   (no neutral discount) on 243 gold + 907 holdout: sector 943 of 1,150 against 801 for
   the first stage 1, direction balanced recall 0.736 against 0.607. Kept. Rerun with
   `Desktop\Laya stage 1.cmd` on mains power; it resumes from its last checkpoint.
4. Automatic after step 3: the daily LoRA trains from `stage1` when it was kept, and
   from the stock model otherwise. Read two nights of `history.jsonl`.
5. Done: `laya._load` reloads when the weights file under `FINSCRAPE_LAYA_MODEL`
   changes, so a promotion needs no restart.
6. Production: the API on Render keeps `FINSCRAPE_LAYA=0` (512 MB). The ingest Action
   runs Laya on CPU: it installs CPU-only torch, restores the checkpoint from the
   release named by the repo variable `LAYA_RELEASE` (cached per tag), and runs without
   Laya when the variable is unset. `scripts/laya_train/publish.py` creates the release
   and sets the variable; `daily.py` calls it on every promotion. First release:
   `laya-20260930-0019`. Watched 30 Sep with `laya-20260930-0428`: the first run
   downloaded it (cache miss, 4m24s), the next restored it from cache (4m49s); both
   logged "Laya classifier loaded" and stored sectors for every new event.
7. Done (30 Sep): teacher round. 3,537 fresh headlines (3,000 production events and
   one live pass over every worker source), 1,412 left after dropping duplicates,
   known subjects, 870 crypto price alerts and 93 quake reports (a dozen and four
   kept). Claude labelled all 1,412 with sector and direction (the first direction
   labels) and reviewed the 256 earlier `claude -p` labels: 32 were wrong (12.5%),
   mostly war and politics pushed into a sector and ship orders marked energy; the
   daily prompt now carries those rules and asks for direction. Split 4:1 into train
   (1,825) and holdout (337). Scores on 243 gold + 337 holdout, sector through the
   production chain:

   | model | gold | holdout | direction balanced recall (283) |
   |---|---|---|---|
   | stock | 155 | 203 | 0.48 |
   | previous LoRA | 185 | 244 | 0.49 |
   | teacher LoRA | 194 | 268 | 0.58 |
   | teacher LoRA, moves x3 (promoted, `laya-20260930-0428`) | 200 | 273 | 0.65 |

   Direction is scored by balanced recall because 214 of the 283 cases are neutral:
   the plain teacher LoRA reached 227 raw hits mostly by calling almost everything
   neutral (down moves caught fell 23 to 15). Repeating positive and negative cases
   three times fixed that (up 21/36, down 16/33, neutral 189/214) and lifted sector
   too; `daily.py` now trains the same way and promotes only if balanced recall does
   not drop by more than 0.02. Earlier checkpoints: `laya-ft\current-prev-20260929`,
   `laya-ft\current-teacher-20260930`.
8. The 30 Sep 03:30 daily run trained but was stopped before scoring (exit
   0xC000013A). No power event was logged; Windows logged ephemeral TCP port exhaustion at
   03:49, the same minute. "Stop if going on batteries" is now off for this task only
   (30 Sep); read the 1 Oct log to see whether scoring completes.
9. Teacher round 2 (30 Sep, not promoted). The 3,000 events round 1 took were the newest;
   the older production events (to June) plus one live source pass gave 3,120 new headlines
   after the usual cleaning, and 2,352 after collapsing rewrites of the same story (token
   overlap 0.4). Claude hand-labelled the 1,320 with a nonzero stored score or from the live
   pass: 224 up, 138 down, 958 neutral; 4:1 into train (2,881) and holdout (601). The LoRA
   (moves x3, stock base because stage 1 was stopped) scored, on 243 gold + 601 holdout:

   | model | gold | holdout | balanced | up | down | neutral |
   |---|---|---|---|---|---|---|
   | current (`laya-20260930-0428`) | 200 | 484 | 0.684 | 47/90 | 35/58 | 370/399 |
   | round 2 candidate | 194 | 477 | 0.729 | 66/90 | 32/58 | 360/399 |

   It lost 13 sector cases and 3 down calls, so it was not promoted; the labels stay in
   `laya-ft\data` for the nightly run. Down moves are still the weakest class.
10. Down moves (30 Sep): repeating down cases x5 and up x3 on the same data, scored the same
    way on 243 gold + 601 holdout:

    | model | gold | holdout | balanced | up | down | neutral |
    |---|---|---|---|---|---|---|
    | current (`laya-20260930-0428`) | 200 | 484 | 0.684 | 47/90 | 35/58 | 370/399 |
    | down x5, from stock | 194 | 476 | 0.730 | 60/90 | 34/58 | 374/399 |
    | down x5, from current | 202 | 478 | 0.696 | 49/90 | 35/58 | 375/399 |

    Neither was promoted: both lost sector cases (14 and 4) and neither caught one more down
    move, so `daily.py` keeps x3 for both. Training from the current checkpoint cost fewer
    sector cases. Heavier repeats do not help; the next try is more down-move labels.

Checked and dropped (29 Sep): labelling headlines by which SPDR sector ETF moved most
against SPY after them. Only 22 of 72 trading days from June to September had one
clear sector, 16 of them energy, and each day carries about 130 headlines, so a daily
move cannot be pinned on one story.

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
- Read `history.jsonl` and the latest `logs\daily-*.log`: did runs happen, did
  labels arrive, were promotions real gains. Spot-check Claude's labels.

## Gated

G2–G5 were decided by the owner on 28 Sep 2026 and became items 9–11.
