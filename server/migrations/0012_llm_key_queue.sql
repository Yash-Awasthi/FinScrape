-- Order of the LLM key queue (finscrape/analysis/ai_client.py): when each key last
-- answered HTTP 429. Keys are stored only as SHA-256 fingerprints.
CREATE TABLE IF NOT EXISTS llm_key_queue (
    fingerprint TEXT PRIMARY KEY,
    moved_at    TIMESTAMPTZ NOT NULL
);
ALTER TABLE llm_key_queue ENABLE ROW LEVEL SECURITY;
