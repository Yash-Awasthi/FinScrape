-- Score 0 means no call, so it reads OBSERVE (Verdict.from_score since 12 Oct); older rows
-- said CAUTIOUS. The backtest skips both verdicts, so no outcome changes.
UPDATE events SET verdict = 'OBSERVE' WHERE signal_score = 0 AND verdict = 'CAUTIOUS';
-- The Reddit job that filled this table and the route that read it were removed.
DROP TABLE IF EXISTS social_posts;
