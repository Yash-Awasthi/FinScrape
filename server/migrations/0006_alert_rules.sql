-- User alert rules (conditions AND-ed, actions fired on a match) and what fired,
-- moved from the standalone SQLite store.
CREATE TABLE IF NOT EXISTS alert_rules (
    id         TEXT        PRIMARY KEY,
    name       TEXT        NOT NULL,
    conditions JSONB       NOT NULL DEFAULT '[]',
    actions    JSONB       NOT NULL DEFAULT '[]',
    enabled    BOOLEAN     NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_history (
    id          BIGSERIAL   PRIMARY KEY,
    rule_id     TEXT        REFERENCES alert_rules (id) ON DELETE SET NULL,
    event_id    BIGINT,
    action_type TEXT        NOT NULL,
    status      TEXT        NOT NULL,
    fired_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_history_fired ON alert_history (fired_at);
