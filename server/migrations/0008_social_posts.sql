-- Reddit posts the worker reads by RSS; /api/sentiment aggregates them per ticker.
CREATE TABLE IF NOT EXISTS social_posts (
    url           TEXT        PRIMARY KEY,
    subreddit     TEXT        NOT NULL DEFAULT '',
    author        TEXT        NOT NULL DEFAULT '',
    title         TEXT        NOT NULL,
    published_at  TIMESTAMPTZ NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_social_posts_published ON social_posts (published_at DESC);
ALTER TABLE social_posts ENABLE ROW LEVEL SECURITY;
