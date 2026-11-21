-- Which judge wrote each event (plan m1.3.1). Before this, a heuristic row and a
-- model-judged row were indistinguishable unless the reader knew to look at
-- key_metrics->>'prompt_variant', so the dashboard mixed them silently.
--
-- analysis_source ∈ {'model', 'model_repaired', 'heuristic', 'laya'}; 'unknown' is the
-- default for rows written before this migration, so old data is labelled honestly rather
-- than back-filled by guesswork. model_name is empty for rows no model produced.
ALTER TABLE events ADD COLUMN IF NOT EXISTS analysis_source TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE events ADD COLUMN IF NOT EXISTS model_name      TEXT NOT NULL DEFAULT '';

-- /api/accuracy splits hit rate by source, and the dashboard badge reads it per row.
CREATE INDEX IF NOT EXISTS idx_events_analysis_source ON events (analysis_source);
