-- Scenario probability history (plan m4.2.2): one row per recompute that moved the
-- number, so the page can show the trend instead of a single point in time.
CREATE TABLE IF NOT EXISTS scenario_history (
    scenario_id  TEXT NOT NULL,
    probability  DOUBLE PRECISION NOT NULL,
    n_members    INTEGER NOT NULL DEFAULT 0,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scenario_id, computed_at)
);

CREATE INDEX IF NOT EXISTS scenario_history_recent
    ON scenario_history (scenario_id, computed_at DESC);
