-- Telegram chats subscribed to verdict alerts, previously a JSON file in data_dir.
CREATE TABLE IF NOT EXISTS telegram_subscribers (
    chat_id       TEXT        PRIMARY KEY,
    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
