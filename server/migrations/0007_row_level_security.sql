-- Supabase publishes every public table through its Data API to anyone holding the
-- publishable key. RLS with no policies closes that door; the API and worker connect
-- as the table owner, which RLS does not restrict.
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END $$;
