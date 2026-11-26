-- Event-page detail (plan m4.2.1): the text excerpt the call was made from, and the
-- first time each source contributed the story. Both defaulted so old rows stay readable.
ALTER TABLE events ADD COLUMN IF NOT EXISTS excerpt TEXT NOT NULL DEFAULT '';
ALTER TABLE events ADD COLUMN IF NOT EXISTS source_seen JSONB NOT NULL DEFAULT '{}'::jsonb;
