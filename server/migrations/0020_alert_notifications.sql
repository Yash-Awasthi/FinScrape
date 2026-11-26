-- Notification centre (plan m4.3.1): a human mark on what the rules fired, so the
-- alerts list can show read/unread without inventing a second history table.
ALTER TABLE alert_history
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;

-- The centre reads the newest rows first; the 0006 index is ascending on fired_at.
CREATE INDEX IF NOT EXISTS idx_alert_history_fired_desc
    ON alert_history (fired_at DESC);
