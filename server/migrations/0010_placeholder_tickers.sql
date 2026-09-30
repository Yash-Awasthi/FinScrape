-- The LLM wrote N/A, NONE or a dash as the ticker of unlisted entities; clean_tickers
-- now drops them on ingest, and this removes them from stored events.
UPDATE events
SET tickers = COALESCE((
    SELECT jsonb_agg(t)
    FROM jsonb_array_elements_text(tickers) AS t
    WHERE upper(t) ~ '^[A-Z0-9][A-Z0-9.=-]{0,14}$'
      AND upper(t) NOT IN ('NA', 'NONE', 'NULL', 'TBD', 'UNKNOWN', 'PRIVATE', 'UNLISTED')
), '[]'::jsonb)
WHERE jsonb_typeof(tickers) = 'array'
  AND EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(tickers) AS t
    WHERE upper(t) !~ '^[A-Z0-9][A-Z0-9.=-]{0,14}$'
       OR upper(t) IN ('NA', 'NONE', 'NULL', 'TBD', 'UNKNOWN', 'PRIVATE', 'UNLISTED')
  );
