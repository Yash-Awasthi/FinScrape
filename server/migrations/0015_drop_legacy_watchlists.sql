-- Drop the 0004 `watchlists` shape (name PK + JSONB tickers) before 0016 creates the
-- real model. Nothing has read it since the portfolio moved out of SQLite: the only
-- writer was that migration, and no query in this repository names it.
--
-- The guard matters for databases created before this file existed and for re-runs: the
-- drop only fires while the old column is still there.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'watchlists'
          AND column_name = 'tickers'
    ) THEN
        DROP TABLE watchlists;
    END IF;
END $$;
