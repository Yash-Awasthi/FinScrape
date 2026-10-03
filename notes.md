# Notes

What is known about WorldFin and how it runs. Open work lives in `task.md`; finished work
lives in git history.

## Where things stand

As of 3 Oct 2026: live and demo-ready. A fresh clone starts with `make demo`
(`docs/DEMO.md` is the walkthrough).

- Production: SPA on Cloudflare Pages, API on Render, Postgres on Supabase. The Cloudflare
  cron Worker `winfin-ingest-cron` is the only scheduler (GitHub turns off schedules in a
  public repo after 60 days without commits): every `INGEST_EVERY_HOURS` hours it dispatches
  `ingest` (24 since 3 Oct, at 00:10 UTC), plus `telegram-summary` daily at 02:30 UTC,
  `backup` at 21:20 UTC (an encrypted dump kept 14 days) and `score-week` on Saturdays at
  06:00 UTC. `make ingest-every HOURS=1` switches to hourly for demos, which also pings
  `/health` every 10 minutes so Render never sleeps; at 24 the API cold-starts in 30-50 s.
- Analysis: ingest calls TokenHarbor (deepseek, then mimo) through a queue of
  `OPENAI_API_KEY` and the eight `OPENAI_API_KEYS`: a key that answers 429 (its free 7-day
  allowance is spent) goes to the back, and `llm_key_queue` keeps that order between runs.
  The first key is spent until 9 Oct 09:45 UTC. TokenHarbor refuses requests
  from Render (403 `request_forbidden`), so the API analyses only on click with OpenRouter
  free models (`FINSCRAPE_MODEL`, `FINSCRAPE_MODEL_FALLBACK`) and, when all fail, dispatches
  the `analyze` workflow, at most 20 times an hour.
  The LLM reads each page's main text (trafilatura, capped at 6,000 characters), not the
  feed summary or the GDELT slug title: on 3 Oct that took GDELT from ~60 characters to
  4,000-6,000 and world RSS from a median ~200 to ~2,600.
- Sectors: a named S&P 500 company sets the sector; frozen Laya `laya-20261001-1041` labels
  stories that name none. Calls: INVEST at score +3, PULL_OUT at -3.
- Scoring: every call is scored next-day raw and +2 / +4 trading days against SPY, and the
  landing page shows both. `docs/BACKFILL.md` holds the backfill, the weekly jobs and the
  studies behind these choices.
- Telegram: ingest sends INVEST / PULL_OUT alerts through @YashAwasthiBot, and the
  `telegram-summary` Action sends a daily summary.

## Measured, worth not re-deriving

- Track record on 3 Oct: +2 days vs SPY 53.8% of 874 (Wilson 50% to 57%); +4 days 59.0%
  of 846 (56% to 62%). On 2 Oct: next-day raw 58.5% of 342 decisive calls; by first source
  at +4, gdelt 71% of 291, world_rss 54% of 423, coingecko 34% of 53.
- The 76 calls from 22 to 30 Sep hit 42% at +2 days (Wilson 32% to 53%); at +4 they rose
  from 39% of 18 to 48% of 48 (34% to 62%) by 3 Oct, recovering but still below the record. 42 of them came on 29 Sep, so this is one bad market week, not a trend: defence and
  oil PULL_OUT calls, which lost most there, hit 65% of 182 and 70% of 145 at +4 over the
  whole record. The rest were 7 crypto price alerts and 3 tickers from before grounding
  (World Bank as WB, a Hong Kong IPO story as GEM, SpaceX as SPCX). No threshold change.
- CoinGecko price alerts are not registered as a source; rows kept arriving from an old
  writer until 28 Sep and stay in the record.
- Cold `/api/scenarios?window=200` costs ~73 s, almost all Ollama embedding, once per
  process: `embeddings.embed` is LRU-cached and startup warm-up pays it.
- Every scenario is a singleton by design: `_find_duplicate` merges same-story coverage at
  ingest, so corroboration lives in one event's `articles` / `sources`.
- The LLM's reasoning invents technology angles, so Laya reads article text, never the
  reasoning. Laya's checkpoint has no valid calibration for 11+ options, so it is offered
  ten and low confidence reads as `other`.
- About 4,600 heuristic-era rows stay unanalysed on purpose: re-running them costs about
  4.5 hours of the shared LLM key for roughly 600 useful rows, and scenarios and the
  backtest already skip them.
- Events stored before 30 Sep keep ungrounded tickers; since then LLM tickers survive only
  when a text source finds them or the curated map or SEC title agrees with the name.
- GitHub fired the `13,43 * * * *` ingest schedule every 3 to 6 hours, hence the cron Worker.
- Reddit's JSON API and StockTwits answer 403 everywhere; Reddit RSS answers a GitHub runner
  once, then 429s. Only 6 of 26 Live TV channels play in an embed. The Times of Israel feed
  blocks GitHub runners and was removed.

## Known limits

- The rate limiter and response cache live in process memory; on more than one replica each
  keeps its own counts. The upgrade path is Redis.
- `is_public_ip` treats documentation ranges such as `203.0.113.0/24` as private.
- The vendored `finscrape/` tree has its own ruff debt and sits outside `NEW_DIRS`.

## Local hazards

- `tests/server/` truncates its database, so it reads `WORLDFIN_TEST_DATABASE_URL` and
  refuses any database not named `*_test` (locally `worldfin_test` on port 5434).
- The nexus Docker stack holds 8000, 5432, 6379, 3000 and 4173. WorldFin's API runs on 8010
  (`WORLDFIN_PORT=8011` while `adapfit-backend-1` holds 8010); compose publishes Postgres
  on 5433, Redis on 6380, Grafana on 3002; Playwright previews on 4183. The native Postgres
  17 service runs on 5434 and `.env` points `WORLDFIN_DATABASE_URL` there.
- `data/finscrape.db` and `data/portfolio.db` are left from the retired SQLite mode; no
  code reads them.
- Laya (CPU torch) loads ~800 MB on first use and takes ~2 s per article; `FINSCRAPE_LAYA=0`
  turns it off. Ollama must serve `nomic-embed-text`, and runs CPU-only
  (`CUDA_VISIBLE_DEVICES=-1`) or it takes the GPU.
- Windows tasks: `WorldFin DB backup` dumps `worldfin` into `backups/` nightly (newest 14
  kept; `make restore FILE=...`); `WorldFin backfill weekly` rewrites `data/backfill/` on
  Saturdays; `WorldFin Laya daily` is disabled.
- History was rewritten on 30 Sep 2026 and the repository recreated on 1 Oct; the old
  history is in `../fin-scrape-history-backup-20260930.bundle`.
