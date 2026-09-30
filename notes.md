# Notes

Handover log. Open work lives in `task.md`; this file records what is known and
what has closed.

## Where things stand

As of 29 Sep 2026: demo-ready. A fresh clone starts with `make demo`; production is
Pages + Render + Supabase with ingest dispatched by a Cloudflare cron Worker (item 9
lists what the owner still has to do). `docs/DEMO.md` is the walkthrough. Gates
green: ruff, pyright, selfcheck, 1164 pytest with the test database, 66 vitest,
build, 5 Playwright, CI `e2e-live`. The portfolio feature is gone (WorldFin tracks
every event, not holdings). Laya (item 11) is parked; ReliefWeb (G1) is gated.

## Measured, worth not re-deriving

- Cold `/api/scenarios?window=200` is ~73s, almost entirely Ollama embedding
  (~360 ms/subject at `_PREFETCH_WORKERS = 6`). Cosine clustering is ~2.5s.
- That cost is once per process, not once per cache TTL — `embeddings.embed` is
  LRU-cached, so a TTL miss with a warm process rebuilds in ~0.04s. Startup
  warm-up now pays it, and the first caller sees single-digit milliseconds.
- Every scenario is a singleton and that is correct: `_find_duplicate` merges
  same-story coverage at ingest, so corroboration lives in one event's
  `articles`/`sources`, never in cluster size.
- Sector labels on 74 events after the Laya chain: 0 blank (was 31%),
  `technology` 11 (was 27% of labelled events), `other` 17, mostly political.
- The LLM's reasoning text itself invents technology angles ("affecting
  semiconductor firms"), so Laya is given article text, never the reasoning.
- Laya's checkpoint has no valid calibration for 11+ options, so the sector
  question offers ten and treats low confidence as `other`.
- Sector accuracy on the 56-headline gold set (`tests/fixtures/sector_gold.json`,
  labels provisional until the owner reviews them), headline only and no LLM:
  64.3% from keywords and named companies, 73.2% with Laya added
  (`python -m tests.test_sector_eval`). Laya's misses lean to `other` on
  consumer, materials and energy stories that name no company.
- The backtest used to score every event against the day the worker ran, not
  the days after the event. Re-scored on the event window (close before the
  event's day to the next trading close, `THRESHOLD_PCT` 1%): INVEST 1/8 became
  2/3 and PULL_OUT 5/5 became 5/7, 10 decisive of 40. The pre-fix rows are in
  the session scratchpad only. Scenarios read `thin-data` until the recency
  weight reaches 30 (`MIN_EMPIRICAL_WEIGHT`), and cards show the count (n=10).
- Event tickers: the LLM free-associated megacaps (NVDA on a Gaza shooting). LLM
  tickers now survive only if a text source finds them or the article names the
  company. Stored events before 23ae9432 keep their old tickers. The keyword map
  still gives defence names (LMT, NOC, RTX) to political stories such as Meloni's.
- Track record, 29 Sep, re-scored per ticker in the called direction: 321 decisive calls,
  59.5% (PULL_OUT 175/292, INVEST 16/29), nearly all June-July. By first source:
  world_rss 64% (140), gdelt 62% (115), coingecko 51% (43). By score: PULL_OUT at -2
  56% (205, mean called move -0.12%), -3 67%, -4 79%; INVEST at +3 65%.
- GitHub fired the `13,43 * * * *` ingest schedule every 3-6 hours, not every 30 min.
- Reddit: the JSON API and StockTwits answer 403 everywhere; Reddit RSS answers a
  GitHub runner once, then 429s. Only 6 of 26 Live TV channels played in an embed.

## Closed

- Worker re-sent every article to the LLM each cycle; now skips seen URLs (c9158d9e).
- RSS cap starved all but the fastest feeds; feeds interleave before the cap (c9158d9e).
- Same-story merges reached SQLite only; now copied to Postgres (c9158d9e).
- Correlation rows duplicated every cycle; now one row per signal (c9158d9e).
- Junk tickers (NATO, CIA, indices) filtered (c9158d9e).
- Scenario cards read 51–52% and said "reduce other"; fixed (c9158d9e).
- Local `.env` leaked into tests (1aef71dd); smoke tests used stale settings (43e501ba).
- Playwright reused another stack's server on 4173; e2e now uses 4183 (839e4eeb).
- CI resolved ruff 0.16.9 and failed unchanged code; ruff and pyright pinned (f993fb10).
- Merged into master as PR #5 (4d29557a).
- Company headlines read `other`; named companies now back the sector via `TICKER_SECTOR` (d5b01528). Live: the Amazon headline re-labelled `technology`; Gaza and Pakistan stay `other`.
- Sector chain had no fixed evaluation; gold set and eval test added (6e23cdbc). Numbers above.
- A dead world feed was invisible; each feed has a `world/<key>` health row (949ef769). Live: `/api/health` listed all 32, `eu_commission` WARN.
- GDELT has its own interval, `WORLDFIN_GDELT_INTERVAL_MIN`, default 30 (04030df9). Live: worker logged "gdelt every 30 min"; 429 retries went 1 then 0, too few cycles to credit.
- ETag honours `If-None-Match` lists and `*` (cebdf96b). Live: `/api/stats` answers 304 to both.
- `predict()` read a PULL_OUT hit rate as a rise (9a76547b). Live: Hormuz, Houthi and Putin scenarios flipped from `up` to `down`.
- pytest's 21 warnings fixed at source (efc7af25). Check: `-W error::DeprecationWarning` passes, 0 warnings.
- Full-stack Playwright run, `make e2e-live`, on API 8012 and SPA 4184; not in CI (987421a3). Live: 1 passed.
- Startup scenario warm-up had never run; it passed `Query()` objects to asyncpg (75fdbca5). Live: "scenario cache warmed", first request 0.28s.
- Worker dedup reads Postgres instead of SQLite events (27e5a8f0). Live: a merge landed on Postgres row 59; SQLite stayed at 78 events. Dropping the table is G5.
- Ruff 0.16.9 with its 95 findings fixed; blind excepts give their reason (043f58b0).
- One dead feed marked the API degraded; `world/*` rows now count only when half are down (e1af2dc6). Live: `/api/health` read `ok` with `eu_commission` WARN listed.
- `eu_commission` failed: ec.europa.eu drops every curl_cffi handshake; fastfetch falls back to requests (b3b4b3c6). Live: 9 entries. The six "silent" feeds were alive, just quiet over the weekend.
- Unrelated event tickers came from the LLM; they are now grounded in the text (23ae9432). Live: the Gaza article kept defence and energy names only; Meloni lost INTC, GOOGL, MSFT.
- Backtest scored today's move for every event; it now scores the window after each event (caae4c39, 3415c69f). Live re-score in "Measured" above.
- `empirical` needed one outcome; now 30 weighted outcomes, and cards show n (3e488fab). Live: all 6 scenarios read `thin-data`, n=10.
- CI actions bumped to current majors, runners pinned to ubuntu-24.04, Node 24 (15ec3d59, d577a546). setup-uv has no floating major tag, so it is pinned to v10.2.0.
- `make e2e-live` runs in CI against a Postgres service (3e76990c). Check: CI run 36467907073, all jobs green.
- `WORLDFIN_ENV=production` refuses the default key and CORS `*` (c735ecaa). Live: the API refused to start with CORS unset.
- GDELT 429s over several cycles (item 6): at 30 minutes 7 of 9 requests throttled and 2 of 3 cycles failed; at 15 minutes 6 of 6 throttled. The interval does not help; item 12 moves to GDELT's export files.
- Backend CI ran no DB tests; it now has a Postgres service and `WORLDFIN_REQUIRE_PG` fails the run if the database is missing (569c0847). Check: CI backend 1147 passed, 0 skipped.
- Sector keywords were read from whole articles; now headline and lede only (1ffdb127). Live: the Meloni article went from 5 keyword tickers to none; Gaza keeps LMT, RTX, XOM.
- Bare capitals were read as tickers (IE, II, KBRA); only $TICK, (TICK) and exchange-prefixed symbols count now (6556dd57). Old events keep their tickers. The "mojibake" was console display only; stored titles are clean.
- GDELT moved from the DOC API to the 15-minute events export (0ed1af47): no rate limit, geo included, titles from URL slugs, kept only when the entity map ties them to a sector. Live: one cycle fetched 30, inserted 2, merged 2, zero 429s. Interval back to 15 min.
- One store: portfolio (1a6bfafc), Telegram subscribers (c6a7e752), alert rules and history (4337630e) and the email digest (65442944) moved to Postgres; the standalone SQLite mode is retired (8eaa40d2). `main.py` keeps `trading`, `quotes` and `devtools`; the digest is `python -m worker.digest daily|weekly`. Live: portfolio and alert-rule CRUD round-trip, a digest of 18 events built, the pipeline merged a repeat into its Postgres row.

- Scenario-heavy PULL_OUT came from asymmetric thresholds (-2 was PULL_OUT, +2 only OBSERVE); PULL_OUT now needs -3 (ea55ba75). Stored verdicts keep their label, by owner decision. The landing hit rate states what it counts (c32706d5).
- A fresh clone could not start: compose read a gitignored password file and the seed needed host Python (74245893). Check: clean clone, `make demo` and the no-Docker path both served events.
- Correlations had never stored a row: events carried the worker key instead of the tiered tag, and `--once` always hit the first-run gate (6b67eafb). Live: new rows read `gdelt/slguardian.org:wire`; signals wait for tagged events to fill the 24h window.
- Live TV pruned to the six channels whose embed plays (f556dd87); subjects keep their casing (841b2d35); prediction cards name event and verdict (e1be4904); CoinGecko price rows out of scenarios (7ccd2783); retired sources leave the health list (af8dee62). Live: verified in Playwright on production, zero console errors.
- Portfolio feature removed on owner request (dbb6357d); its tables are left in place.
- Sentiment reads Reddit posts the worker stores from one RSS fetch per run (2dd328b0). Live: an ingest run stored 100 posts; the panel shows four NVDA posts.
- Ingest dispatched every 30 min by the Cloudflare cron Worker `winfin-ingest-cron` (0293b598); it needs its GH_TOKEN secret (item 9).
- Demo script rewritten (9019d1a5). Merged as PR #11 (942f9e59).
- uv.lock was gitignored, so CI and ingest resolved fresh and broke on regex 2026.9.29 (no wheels); the lock is committed now (PR #14). Check: CI green, a dispatched ingest run succeeded.
- Crypto alerts: the ingestor has not been registered since June, and the last alert (from the old Neon-era writer) landed on 28 Sep; subjects keep punctuation since 841b2d35. Migration 0009 gives the 934 stored alerts their sign and decimal back ("dropped 98" becomes "dropped -9.8%"). No per-cycle cap: nothing emits alerts any more.
- Demo readiness (30 Sep list) re-checked: `/api/accuracy` 323 decisive calls, 59.4% (PULL_OUT 176/294, INVEST 16/29), matching the 29 Sep re-score; since the -3 PULL_OUT rule, 30 of 321 new events are PULL_OUT (26% before). The owner keeps the live hit rate on the landing page. The 54 heuristic rows from the qwen 429s go through the new `reanalyse` Action (`gh workflow run reanalyse.yml -f days=7`).

## Local hazards

- `tests/server/` truncates its database, so it reads
  `WORLDFIN_TEST_DATABASE_URL` and refuses any database not named `*_test`.
  Locally that is `worldfin_test` on port 5434 (set as a Windows user variable).
- The nexus Docker stack holds 8000, 5432, 6379, 3000 and 4173, and another local
  project (`adapfit-backend-1`) took 127.0.0.1:8010 on 29 Sep; while it runs, start
  WorldFin's API with `WORLDFIN_PORT=8011`. WorldFin's API normally runs on 8010; compose publishes Postgres on 5433, Redis on 6380, Grafana on
  3002; Playwright previews on 4183. The native Postgres 17 service runs on 5434
  and `.env` points `WORLDFIN_DATABASE_URL` there.
- Everything lives in Postgres. `data/finscrape.db` and `data/portfolio.db` are
  left on disk from the retired standalone mode; no code reads them. The 155
  "Test Rule" rows in the former were written by a test that used the real file.
- Laya (`pip install laya`, CPU torch) loads ~800MB on first use and takes ~2s
  per article on CPU. `FINSCRAPE_LAYA=0` turns it off.
- Local run needs Ollama serving `nomic-embed-text`; `qwen2.5:7b` via
  `OPENAI_BASE_URL` works for the analysis LLM at roughly 20s per article.
- A nightly Windows task "WorldFin DB backup" dumps `worldfin` into `backups/`
  (newest 14 kept); `make restore FILE=...` restores one.
