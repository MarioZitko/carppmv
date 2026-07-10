"""Centralized settings, loaded once from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    debug: bool = False
    database_url: str = "postgresql+asyncpg://localhost/carppmv"

    # Comma-separated list of origins allowed to call the API from a browser
    # (the Next.js frontend runs on a different port/host in dev and prod).
    cors_allow_origins: str = "http://localhost:3000"

    # HRK→EUR fixed conversion rate used when normalizing pre-euro catalogue prices.
    hrk_to_eur_rate: float = 7.53450

    # Used by app/catalogue/llm_mapper.py for per-sheet column mapping during
    # catalogue ingestion. Required only when running ingestion, not for
    # normal API operation — so no default/validation failure if unset.
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v4-flash"

    # mobile.de on-demand scraping via Apify actor (mobile.de is behind Akamai
    # Bot Manager — direct scraping fails, see docs/MOBILE_DE_APIFY_SPEC.md).
    apify_api_token: str = ""
    apify_mobile_de_actor_id: str = "ivanvs/mobile-de-scraper"
    apify_call_timeout_seconds: int = 60
    listing_cache_ttl_hours: int = 24
    daily_apify_budget_calls: int = 200  # safety ceiling, degrade gracefully above

    # Abuse protection for the mobile.de/Apify on-demand path — Cloudflare Turnstile
    # bot-check, per-IP rate limiting, and IP hashing (never store raw client IPs).
    turnstile_secret_key: str = ""  # empty ⇒ verification disabled (dev)
    ip_hash_salt: str = "change-me"
    rate_limit_per_ip_hour: int = 10
    rate_limit_per_ip_day: int = 30


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() is parsed once per process, not per request."""
    return Settings()