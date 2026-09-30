# WorldFin — Architecture (as built, Phases 0–4)

How the system is wired today. Frontend (globe/panels) is Phase 5+; this reflects the
backend + worker + correlation foundation. See [current tasks](../task.md) and
[local readiness](LOCAL-READINESS.md) for the maintained workflow and verification.

## Services (docker-compose)

```
            ┌──────────────┐         ┌────────────────────────────────────┐
            │   worker     │  writes │             Postgres 16             │
            │ (APScheduler)│ ───────▶│ events · correlations · scrape_runs │
            │ scrape→judge │         │ source_health · accuracy · ai_cache │
            │ →geocode→corr│         └───────────────┬────────────────────┘
            └──────┬───────┘                         │ asyncpg pool (+jsonb codec)
                   │ reuses finscrape brain          │
                   ▼                    ┌────────────▼─────────────┐
            FinScrapePipeline           │   api (FastAPI/uvicorn)  │
            ._analyze_article           │  REST + WS               │
                                        │  /api/events /stats      │
                                        │  /dates /ai/analyze      │
                                        │  /correlations /health   │
                                        │  WS /api/ws              │
                                        └──────────────────────────┘
```

- **postgres** — datastore. Schema in `server/migrations/0001_init.sql`, applied idempotently
  on api/worker startup by `server/db.py:run_migrations` (tracked in `schema_migrations`).
- **api** (`server/`) — FastAPI app (`server/app.py:create_app`). Lifespan opens the asyncpg
  pool + runs migrations. Routers under `server/routes/`.
- **worker** (`worker/`) — separate long-running process (`worker/main.py`), `AsyncIOScheduler`,
  one interval job per source + a post-scrape correlation pass.
- **redis** — optional (compose profile); the seam for multi-replica WS fan-out + rate-limit
  (Phase 8). Not required in v1.

LLM is **BYOK or local Ollama**, shared with finscrape via env (`OPENAI_BASE_URL` /
`OPENROUTER_API_KEY` / `FINSCRAPE_MODEL`). Typed settings: `server/settings.py`.

## Data flow

1. **Worker cycle** (`worker/runner.py:Worker.run_source`): a source producer
   (`worker/sources.py`) fetches articles (world RSS) or `RawGeoEvent`s (keyless ingestors) →
   blocking scrape/LLM/market work runs in `asyncio.to_thread` → `FinScrapePipeline._analyze_article`
   produces a `FinEvent` → `server/geocode.py:geocode_event` attaches lat/lon (explicit ingestor
   coords win, else country centroid) → `server/ingest.py:ingest_events` upserts.
2. **Dedup** is atomic: a deterministic `content_hash` (normalized subject + canonical first-article
   URL + UTC day) with a UNIQUE constraint + `ON CONFLICT DO NOTHING`.
3. **Correlation** (`worker/runner.py:run_correlations` → `server/correlate.py`): recent events are
   clustered (Jaccard) and run through the detectors; emitted signals persist to `correlations`.
4. **API reads** (`server/queries.py`): the feed, stats, and dates all use the **same** half-open
   `[day, day+1)` UTC bounds (`server/ingest.py:day_bounds`).
5. **Live updates**: `server/ws.py` broadcasts `init`/`new_events`/`ai_updated`/`pong`. API-side
   ingest broadcasts directly; worker→client broadcast waits on the Redis seam (Phase 8).

## The three root-cause bug fixes (vs the old Workers/D1 dashboard)

1. **~4× duplication** → deterministic `content_hash` UNIQUE + `ON CONFLICT DO NOTHING` (atomic;
   no read-then-write race, no fragile `instr(articles,url)` substring match).
2. **Stat/feed count mismatch** → one `day_bounds` convention reused by feed/dates/stats.
3. **Timezone drift** → `parse_timestamp` normalizes everything to UTC `TIMESTAMPTZ` at ingest;
   day derived as `(timestamp AT TIME ZONE 'UTC')::date`; `last_update = MAX(created_at)`.

## Reuse map (the finscrape "brain")

| Capability | Module |
|---|---|
| event→entity→judge fusion | `finscrape/pipeline.py:FinScrapePipeline._analyze_article` |
| data model | `finscrape/models` (`FinEvent`, `ScrapedArticle`, `Verdict`) |
| LLM backends (BYOK/Ollama) | `finscrape/analysis/ai_client.py` (extraction); `server/ai.py` (analyze shape) |
| world-widened prompt | `finscrape/analysis/prompts.py` |
| world feeds + tiers | `finscrape/scrapers/world/feeds.py` |
| keyless ingestors | `finscrape/ingestors/` |
| correlation algorithm | `server/correlate.py` (independent port; spec = PLAN Appendix A) |

## Analysis pipeline (the finscrape brain)

`finscrape/pipeline.py:FinScrapePipeline._analyze_article` is the fusion entry point (see the Reuse
map above). Per article: scrape → freshness gate → `call_ai` (or council) → relevance gate → NLP
enrich → ticker fusion → market data → heuristic score → divergence check → confidence fuse. The
subsections below describe the pieces that changed in the 2026-08-16 analysis-layer hardening pass
and the deliberation/quant follow-on that landed the same day; see
[`../task.md`](../task.md) for current work.

**Ticker resolution.** `finscrape/analysis/ticker_map.py` is the single company-name-to-ticker map;
`finscrape/entity_map.py` is the separate sector/region-to-ticker map used for geopolitics headlines
that name no company. Both share the word-boundary matcher in `entity_map._matches`, so a bare name
like "arm" or "target" cannot fire on a substring inside "pharma" or "price target". The resolved
ticker list is filtered through `finscrape/analysis/validator.py:clean_tickers(tickers, text=...)`,
which only lets a stopword-listed word (`NOW`, `ALL`, `IT`, `AI`, `KEY`, `GO`, `ONE`, …) through when
the source text carries it as an explicit `$TICK` or `(TICK)` marker; both `finscrape/pipeline.py`
and `push_to_dashboard.py` pass the article text into this call.

**Market boost.** `finscrape/market_data.py:calculate_market_boost` picks the single biggest mover
(by absolute percent change) across the resolved tickers and returns a boost signed to match that
mover's direction: `±1` at `≥5%`, `±2` at `≥10%`, `0` below that. `finscrape/pipeline.py` adds this
to the AI's `signal_score` and clamps the result to `[-5, 5]`.

**Confidence fusion.** `finscrape/analysis/validator.py:fuse_confidence` is the single place all
confidence adjustments combine, called from `finscrape/pipeline.py`. The two multiplicative steps
(`apply_source_credibility`, then `apply_recency_decay`) run before the two additive steps (a `-0.15`
divergence penalty, a `+0.10` breaking-news bonus); the result then clamps to `[0, 1]`. Running the
multipliers first means the divergence penalty always costs exactly `0.15`, regardless of how much
the multipliers already discounted the base confidence.

**Heuristic impact score.** `finscrape/analysis/validator.py:calculate_heuristic_score` converts the
event type's base impact to log-odds (`logit_base = log(base / (1 - base))`), adds magnitude-word and
extracted-figure boosts, and runs the sum through a sigmoid. A zero boost returns the base impact
unchanged — there is no double-counting.

**Council crash handling.** `finscrape/agents/base.py:AgentVerdict` carries an `error` flag, set
whenever an agent raises or its response fails to parse. `finscrape/agents/council.py`'s
`_build_consensus` computes every consensus number — score, agreement, confidence, dissent,
risks/opportunities — only from verdicts with `error=False`; a council where every agent crashed
reports `consensus_confidence=0.0` and a `failed_agents` count instead of folding a crashed agent's
implicit verdict into the average.

**Multi-round debate.** `AgentCouncil(rounds=...)` (or `FINSCRAPE_COUNCIL_ROUNDS`, default `1`) runs
round 1 blind via `_run_agents`, then for each further round calls `_run_rebuttal_round`, which
dispatches `agent.rebut(title, text, opponents, metadata, round_num, market_facts)` for every agent
in a single `ThreadPoolExecutor` batch — one dispatch per round, not one per agent per round. Each
agent sees a fenced one-line-per-opponent transcript (name, score, verdict, a one-sentence stance)
built by `finscrape/agents/base.py:BaseAgent.rebut`, wrapped in the same `ARTICLE_FENCE_START`/
`ARTICLE_FENCE_END` markers used for untrusted article bodies, and may change its score. Agents that
errored in the prior round are dropped from the transcript, not shown as an opponent. `deliberate()`
returns a `CouncilVerdict.score_history`, one `{agent_name: score}` snapshot per round, so a caller
can see who moved and by how much. With `rounds=1` (the default), no transcript block is ever built
and the prompt is byte-identical to a single blind pass.

**Judge.** `finscrape/agents/judge.py:judge_debate(transcript, stats, lessons=None)` is an optional
extra LLM call (`AgentCouncil(judge=True)`, on by default for the pipeline's council) that reads
every agent's full verdict + reasoning plus the arithmetic consensus (`consensus_score_raw`,
`agreement_level`, `dissenting_agents`) and hands down its own score/confidence/verdict, explaining
in its rationale whether and why it agrees with or overrides the arithmetic mean. If the judge call
fails or its response does not parse, `judge_debate` returns `None` and `_build_consensus` falls back
to the arithmetic consensus unchanged — `CouncilVerdict.judged` records which happened, and
`consensus_score_raw` always holds the untouched arithmetic mean regardless. Model selection is
`FINSCRAPE_JUDGE_MODEL`, independent of the debating agents' model.

**Quant ground truth.** `finscrape/market_data.py:compute_indicators(closes, highs, lows)` is pure
list arithmetic (no TA-Lib, no pandas) computing `rsi14`, `sma20`/`sma50`, `atr_pct`, `ret_5d`, and
`pct_from_52w_high`; it returns `{}` on fewer than `MIN_INDICATOR_BARS` (50) bars rather than emit a
partial/misleading result. `get_indicators(tickers)` wraps it with one batched 1-year
`yf.download` per call and the same TTL-cache pattern as `get_market_data`, degrading to `{}` on any
fetch error. `finscrape/pipeline.py:_analyze_with_council` resolves tickers with the same
`resolve_tickers` used by `_heuristic_only`, fetches their indicators, and passes the result to
`council.deliberate()` as `market_facts` — the council itself never calls yfinance. Each agent's
prompt renders `market_facts` as a GROUND TRUTH block (`finscrape/agents/base.py:render_market_facts`)
telling the agent to anchor to the given numbers, never invent its own, and flag a conflict instead.
After parsing, `finscrape/analysis/validator.py:check_number_conflicts` regexes the agent's own
reasoning for a stated value of a known indicator name close by (`"RSI is 82"` against a computed
`rsi14=31.2`, for example) within a tolerance, and sets `AgentVerdict.number_conflict` when it
disagrees; `_build_consensus` discounts `consensus_confidence` per flagged survivor, and the judge's
transcript rendering tags a flagged verdict `[NUMBER CONFLICT]`. The regex only catches the
`"NAME ... number"` shape within a short window — indirect phrasing isn't caught and short aliases
like "atr" can false-positive; real number-linking (NER over the reasoning) is the upgrade path if
either starts costing real accuracy.

**Accuracy feedback into the judge.** `finscrape/accuracy.py:AccuracyTracker.get_lessons(tickers,
source, event_type, limit=5)` is a read-only SQL query over the existing `signal_outcomes` table (no
new table, no migration): per-ticker and per-source hit rate, average realized move, and the last
`limit` incorrect calls. It returns `{}` on a cold or no-match database. `_analyze_with_council`
fetches lessons for the article's resolved tickers and source, and passes them into
`council.deliberate(..., lessons=...)`, which forwards them to `judge_debate()` only —
`finscrape/agents/judge.py:format_lessons_block` renders them into a `LESSONS` block the debating
agents never see, so the judge alone can weigh "this ticker/source has missed before" without
biasing the independent per-agent scores.

**Prompt template safety.** `finscrape/analysis/prompts.py:render_prompt` fences the article body
between literal markers, strips any `{{`/`}}` from it, and substitutes it before the title, so
neither the body nor the title can forge a placeholder that hijacks the other slot.
`EVENT_TYPES_PIPE` is built once from `constants.VALID_EVENT_TYPES` at import time, so the prompt's
allowed event types and the validator's accepted set cannot drift apart. Both prompt-registry
variants (`finscrape/analysis/prompt_registry.py`, v1/v2 for the accuracy A/B split) reuse this same
prompt and render path.

**Not present:** `finscrape/analysis/multi_model.py` (cross-provider agreement scoring) was removed;
nothing in the pipeline called it. Relationship extraction and coreference resolution are not
implemented in `finscrape/analysis/nlp.py` despite earlier documentation claiming otherwise —
`nlp.py` does NER, entity disambiguation, ticker resolution, and financial metric extraction only.
`temporal.py` shares a single spaCy parse with `nlp.py` rather than re-parsing the article.

## Testing

- Pure logic is unit-tested offline (dedup/timezone, geocode, ingestor parsers, correlation
  detectors, STALE derivation): `tests/server/`, `tests/test_world_phase2.py`,
  `tests/test_worker_phase3.py`, `tests/test_correlate_phase4.py`.
- The council/judge/quant layer is unit-tested with the AI client stubbed out, no network calls:
  `tests/test_debate.py` (rebuttal rounds, `score_history`, the `rounds=1` no-op path),
  `tests/test_judge.py` (judge override vs. arithmetic fallback), `tests/test_indicators.py`
  (`compute_indicators` on synthetic price series, GROUND TRUTH reaching the prompt, number-conflict
  flagging), `tests/test_lessons.py` (`get_lessons` read-back, its prompt wiring into the judge only).
- DB-dependent paths are **skip-ready** integration tests (`tests/server/test_*integration.py`)
  that auto-skip without Postgres and run under `make up` / CI (postgres service).
- `make lint` / `make fmt-check` / `make selfcheck` / `make test` — 1212 tests, 5 skip without Postgres.

## Known gaps / deferred

- Live `make up` verify (DB+LLM) pending docker; integration tests are ready.
- Worker `get_market_data` (`yf.download`) per-article cost → Phase 8 cache/stub.
- Worker→client WS fan-out needs Redis: `server/pubsub.py` publishes and subscribes when
  `WORLDFIN_REDIS_URL` is set and no-ops otherwise, so single-process runs need nothing.
- `detect_prediction_leads_news` reads AI ticker impacts, so it only sees events that were
  actually analysed; the worker ingest path does not analyse on insert.
- `_topic_mentions_for_symbol` covers the 25 tickers the entity index and the topic keyword
  sets share. A symbol outside that overlap still reads zero related coverage.
