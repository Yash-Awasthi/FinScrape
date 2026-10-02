"""Typed settings for the WorldFin backend (pydantic-settings).

One typed object, imported everywhere — no scattered os.getenv. Reads from the
process env / .env. BYOK and Ollama keys are the SAME ones finscrape already uses
(OPENAI_BASE_URL / OPENROUTER_API_KEY), so a single .env drives both halves.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository-published value, present verbatim in .env.example and as the docker-compose
# fallback; startup warns during any deployment that leaves FINSCRAPE_API_KEY unset.
DEFAULT_API_KEY = "local-dev-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False
    )

    # --- Database ---
    # asyncpg DSN. Compose injects this; default points at the compose service.
    database_url: str = Field(
        default="postgresql://worldfin:worldfin@localhost:5432/worldfin",
        validation_alias="WORLDFIN_DATABASE_URL",
    )
    db_pool_min: int = Field(default=2, validation_alias="WORLDFIN_DB_POOL_MIN")
    db_pool_max: int = Field(default=10, validation_alias="WORLDFIN_DB_POOL_MAX")
    run_migrations_on_startup: bool = Field(
        default=True, validation_alias="WORLDFIN_RUN_MIGRATIONS"
    )

    # "production" turns the warnings below into refusals to start.
    env: str = Field(default="development", validation_alias="WORLDFIN_ENV")

    # --- Ingest auth (every mutating route: POST /api/events, the alert
    # routes, and the vendored /api/v1 signal-ingest routes) ---
    api_key: str = Field(default=DEFAULT_API_KEY, validation_alias="FINSCRAPE_API_KEY")

    # --- LLM (shared with finscrape: BYOK or local Ollama) ---
    openai_base_url: str = Field(default="", validation_alias="OPENAI_BASE_URL")
    # Bearer token for that base URL. Local Ollama ignores it, but any hosted
    # OpenAI-compatible endpoint (LiteLLM, vLLM behind auth, a proxy) rejects the
    # request without it — finscrape.analysis.ai_client has always read this.
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    ai_model: str = Field(default="auto", validation_alias="FINSCRAPE_MODEL")
    # Comma-separated, tried in order when ai_model fails; same variable ingest reads.
    ai_model_fallback: str = Field(
        default="", validation_alias="FINSCRAPE_MODEL_FALLBACK"
    )
    # When every model above fails, /api/ai/analyze dispatches the `analyze` workflow in
    # this repo with a token allowed to run Actions. Unset leaves the heuristic answer.
    analyze_dispatch_repo: str = Field(
        default="", validation_alias="ANALYZE_DISPATCH_REPO"
    )
    analyze_dispatch_token: str = Field(
        default="", validation_alias="ANALYZE_DISPATCH_TOKEN"
    )
    analyze_dispatch_ref: str = Field(
        default="master", validation_alias="ANALYZE_DISPATCH_REF"
    )
    analyze_dispatch_per_hour: int = Field(
        default=20, validation_alias="ANALYZE_DISPATCH_PER_HOUR"
    )

    # --- Optional infra ---
    redis_url: str = Field(default="", validation_alias="WORLDFIN_REDIS_URL")
    # Telegram bot token for outbound alerts + the inbound webhook (Phase 13).
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    # Shared secret echoed by Telegram in X-Telegram-Bot-Api-Secret-Token. The webhook
    # URL is public and its body is attacker-controllable, so commands are only acted
    # on when this is set and matches — register it with setWebhook(secret_token=...).
    telegram_webhook_secret: str = Field(
        default="", validation_alias="TELEGRAM_WEBHOOK_SECRET"
    )

    # --- Feature flags (default off; flip on as phases land) ---
    enable_council: bool = Field(
        default=False, validation_alias="WORLDFIN_ENABLE_COUNCIL"
    )
    enable_correlation: bool = Field(
        default=True, validation_alias="WORLDFIN_ENABLE_CORRELATION"
    )

    # --- Worker (Phase 3) ---
    worker_interval_minutes: int = Field(
        default=15, validation_alias="WORLDFIN_WORKER_INTERVAL_MIN"
    )
    # GDELT publishes its events export every 15 minutes; its own knob stays so a
    # deployment can slow it independently of the feeds.
    gdelt_interval_minutes: int = Field(
        default=15, validation_alias="WORLDFIN_GDELT_INTERVAL_MIN"
    )
    worker_max_articles: int = Field(
        default=20, validation_alias="WORLDFIN_WORKER_MAX_ARTICLES"
    )
    # Days kept in correlations / scrape_runs / ai_analysis_cache; 0 keeps forever.
    retention_days: int = Field(default=90, validation_alias="WORLDFIN_RETENTION_DAYS")
    source_stale_after_minutes: int = Field(
        default=60, validation_alias="WORLDFIN_SOURCE_STALE_MIN"
    )
    # Build the scenario cache at boot so the first caller doesn't pay the full
    # Ollama embedding pass. Off in tests, which have neither Ollama nor a DB.
    warm_scenarios_on_startup: bool = Field(
        default=True, validation_alias="WORLDFIN_WARM_SCENARIOS"
    )

    # --- Server ---
    host: str = Field(default="0.0.0.0", validation_alias="WORLDFIN_HOST")
    # PaaS hosts (Render/Koyeb/Fly) inject $PORT — bind whatever they assign.
    port: int = Field(
        default=8010, validation_alias=AliasChoices("WORLDFIN_PORT", "PORT")
    )
    cors_origins: str = Field(default="*", validation_alias="WORLDFIN_CORS_ORIGINS")

    # --- Hardening (Phase 8) ---
    # Per-IP sliding-window rate limit. 0 disables (handy in tests).
    rate_limit_per_min: int = Field(
        default=120, validation_alias="WORLDFIN_RATE_LIMIT_PER_MIN"
    )
    # Add HSTS only when the API is served over TLS (off by default; nginx/dev is http).
    enable_hsts: bool = Field(default=False, validation_alias="WORLDFIN_ENABLE_HSTS")
    # Emit weak ETags + honor If-None-Match (304) on GET JSON. On by default.
    enable_etag: bool = Field(default=True, validation_alias="WORLDFIN_ENABLE_ETAG")

    # --- Observability (Phase 9) ---
    # Emit one-line JSON logs instead of the human format (set on in containers so
    # promtail/Loki get structured records). Off by default for readable local dev.
    log_json: bool = Field(default=False, validation_alias="WORLDFIN_LOG_JSON")
    log_level: str = Field(default="INFO", validation_alias="WORLDFIN_LOG_LEVEL")
    # Port the worker exposes its Prometheus /metrics on (the API serves /metrics on
    # its own HTTP port). 0 disables the worker metrics server.
    metrics_port: int = Field(default=9100, validation_alias="WORLDFIN_METRICS_PORT")

    @property
    def uses_default_api_key(self) -> bool:
        """True while the mutating routes still accept the published default key."""
        return self.api_key == DEFAULT_API_KEY

    def production_problems(self) -> list[str]:
        """Settings the API refuses to start with under WORLDFIN_ENV=production."""
        if self.env.lower() != "production":
            return []
        problems = []
        if self.uses_default_api_key:
            problems.append("FINSCRAPE_API_KEY is the published default")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("WORLDFIN_CORS_ORIGINS must list the dashboard origin(s)")
        return problems

    @property
    def llm_model_unset(self) -> bool:
        """True when an OpenAI-compatible backend is configured but no model is named.

        "auto" is a placeholder, not a model id — no backend resolves it, so every call
        404s and `analyze_event` quietly returns its heuristic instead. Set
        FINSCRAPE_MODEL to a real id from the backend's /models list.
        """
        return bool(self.openai_base_url) and self.ai_model in ("", "auto")

    @property
    def has_llm(self) -> bool:
        """True if any LLM backend is configured (Ollama proxy or OpenRouter BYOK)."""
        return bool(self.openai_base_url or self.openrouter_api_key)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Tests can clear with get_settings.cache_clear()."""
    return Settings()
