-- Excess return over SPY in the called direction, +2 and +4 trading days from the last
-- close before the news (docs/LAYA_PLAN.md). NULL until that window has closed.
ALTER TABLE accuracy_outcomes ADD COLUMN IF NOT EXISTS ex2 DOUBLE PRECISION;
ALTER TABLE accuracy_outcomes ADD COLUMN IF NOT EXISTS ex4 DOUBLE PRECISION;
ALTER TABLE accuracy_outcomes ADD COLUMN IF NOT EXISTS correct2 BOOLEAN;
ALTER TABLE accuracy_outcomes ADD COLUMN IF NOT EXISTS correct4 BOOLEAN;
