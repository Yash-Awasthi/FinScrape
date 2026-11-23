-- Watchlists, the real model (plan m4.1.1). 0015 drops the unused 0004 shape first.
-- owner_key is an opaque string (today "default", later the API key's fingerprint), so
-- the table needs no accounts to be useful.
CREATE TABLE IF NOT EXISTS watchlists (
    id         BIGSERIAL   PRIMARY KEY,
    owner_key  TEXT        NOT NULL DEFAULT 'default',
    name       TEXT        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_key, name)
);

-- kind narrows what `value` means: a symbol, a sector label, a topic word or a region.
-- The CHECK is the contract the API validates against, not an open string.
CREATE TABLE IF NOT EXISTS watchlist_items (
    id            BIGSERIAL   PRIMARY KEY,
    watchlist_id  BIGINT      NOT NULL REFERENCES watchlists (id) ON DELETE CASCADE,
    kind          TEXT        NOT NULL CHECK (kind IN ('ticker', 'sector', 'topic', 'region')),
    value         TEXT        NOT NULL CHECK (length(btrim(value)) BETWEEN 1 AND 80),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (watchlist_id, kind, value)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_items_list ON watchlist_items (watchlist_id);
