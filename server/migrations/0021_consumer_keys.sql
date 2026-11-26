-- Per-consumer API keys (plan m4.4). The plaintext exists only in the issue response;
-- the row stores a sha256 hex of it, so a dump of this table cannot be replayed.
CREATE TABLE IF NOT EXISTS consumer_keys (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    tier         TEXT NOT NULL DEFAULT 'read' CHECK (tier IN ('read', 'write')),
    key_hash     TEXT NOT NULL UNIQUE,
    key_prefix   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS consumer_keys_live ON consumer_keys (id) WHERE revoked_at IS NULL;
