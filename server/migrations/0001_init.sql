-- FinScrape schema — Phase 0 (resolves PLAN.md open-investigation #1).
-- Columns mirror finscrape FinEvent (finscrape/models/__init__.py). JSONB for the
-- list/dict fields; scalars as typed columns. TIMESTAMPTZ everywhere, UTC-normalized
-- at ingest, so the ONE half-open [day, day+1) day-bounds convention holds across
-- feed / dates / stats (kills the live count-mismatch + timezone drift — Appendix B).
--
-- Migrations are append-only and idempotent at the file level (CREATE ... IF NOT
-- EXISTS). The runner in server/db.py records applied files in schema_migrations and
-- skips them on reboot — so "migrations idempotent on restart" (Phase 0 Verify) holds.

CREATE TABLE IF NOT EXISTS events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_hash    TEXT        NOT NULL UNIQUE,           -- norm(subject)+canon(url0)+UTC-day
    subject         TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,
    impact_direction TEXT       NOT NULL DEFAULT 'neutral',
    signal_score    INTEGER     NOT NULL DEFAULT 0,        -- -5..+5
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 0.0, -- 0..1
    verdict         TEXT        NOT NULL,
    heuristic_impact DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    divergence_flag BOOLEAN     NOT NULL DEFAULT FALSE,
    reasoning       TEXT        NOT NULL DEFAULT '',
    magnitude       TEXT        NOT NULL DEFAULT 'medium',
    novelty         TEXT        NOT NULL DEFAULT 'standard',
    actionability   TEXT        NOT NULL DEFAULT 'medium',
    sector_impact   TEXT        NOT NULL DEFAULT '',
    -- list/dict fields as JSONB
    tickers             JSONB   NOT NULL DEFAULT '[]'::jsonb,
    sources             JSONB   NOT NULL DEFAULT '[]'::jsonb,
    articles            JSONB   NOT NULL DEFAULT '[]'::jsonb,
    affected_entities   JSONB   NOT NULL DEFAULT '[]'::jsonb,
    second_order_effects JSONB  NOT NULL DEFAULT '[]'::jsonb,
    key_metrics         JSONB   NOT NULL DEFAULT '{}'::jsonb,
    -- geo for the globe
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    -- time: client-supplied event time (UTC-normalized) + server ingest time
    timestamp       TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp  ON events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_verdict    ON events (verdict);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at DESC);
-- JSONB tickers membership queries (?| / @>) use GIN
CREATE INDEX IF NOT EXISTS idx_events_tickers_gin ON events USING GIN (tickers);

-- Correlation signals emitted by the engine (Phase 4).
CREATE TABLE IF NOT EXISTS correlations (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dedupe_key      TEXT        NOT NULL,
    signal_type     TEXT        NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_correlations_detected ON correlations (detected_at DESC);

-- One row per worker scrape cycle (Phase 3).
CREATE TABLE IF NOT EXISTS scrape_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT        NOT NULL DEFAULT 'running',  -- running|ok|partial|failed
    events_ingested INTEGER     NOT NULL DEFAULT 0,
    details         JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Per-source freshness (Phase 3, drives /api/health).
CREATE TABLE IF NOT EXISTS source_health (
    source          TEXT        PRIMARY KEY,
    fetched_at      TIMESTAMPTZ,
    record_count    INTEGER     NOT NULL DEFAULT 0,
    status          TEXT        NOT NULL DEFAULT 'UNKNOWN',  -- OK|STALE|WARN|EMPTY
    last_error      TEXT
);

-- Verdict-vs-realized-price backtest outcomes (Phase 7).
CREATE TABLE IF NOT EXISTS accuracy_outcomes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        BIGINT      REFERENCES events(id) ON DELETE CASCADE,
    ticker          TEXT        NOT NULL,
    verdict         TEXT        NOT NULL,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    price_move_pct  DOUBLE PRECISION,
    correct         BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_accuracy_event ON accuracy_outcomes (event_id);

-- On-demand LLM expansion cache (Phase 1).
CREATE TABLE IF NOT EXISTS ai_analysis_cache (
    cache_key       TEXT        PRIMARY KEY,                -- sha256(model + event id/hash)
    event_id        BIGINT      REFERENCES events(id) ON DELETE CASCADE,
    result          JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
