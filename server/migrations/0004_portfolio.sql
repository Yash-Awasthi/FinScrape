-- Portfolio and watchlists, previously a SQLite file beside the API that an
-- ephemeral host would lose on every restart.
CREATE TABLE IF NOT EXISTS positions (
    ticker        TEXT             PRIMARY KEY,
    shares        DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (shares >= 0),
    avg_cost      DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (avg_cost >= 0),
    current_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    tags          JSONB            NOT NULL DEFAULT '[]',
    updated_at    TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlists (
    name        TEXT        PRIMARY KEY,
    tickers     JSONB       NOT NULL DEFAULT '[]',
    description TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
