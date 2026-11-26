-- Quiet hours per alert rule: {"start": "HH:MM", "end": "HH:MM"} in UTC.
-- An empty object means the rule may fire at any hour.
ALTER TABLE alert_rules
    ADD COLUMN IF NOT EXISTS quiet_hours JSONB NOT NULL DEFAULT '{}'::jsonb;
