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

    # de.wikipedia crawl (app/wikipedia/, offline batch — never in the
    # /calculate request path). Wikimedia's User-Agent policy requires a
    # descriptive UA with a reachable contact; a default library UA is
    # routed into a stricter rate-limit tier, so this is not etiquette.
    wiki_api_url: str = "https://de.wikipedia.org/w/api.php"
    wiki_contact_email: str = "mariozitkovic@gmail.com"
    wiki_user_agent_product: str = "kalkulatoruvoza-co2-crawler/1.0"
    wiki_site_url: str = "https://kalkulatoruvoza.com"
    # Bot-password credentials (Special:BotPasswords). Optional: the crawler
    # runs anonymously without them, just at the lower concurrency/rate tier.
    wiki_bot_username: str = ""
    wiki_bot_password: str = ""
    # Hard ceiling, not a perf knob — 3 is the authenticated concurrency limit
    # in Wikimedia's API etiquette guidance. Do not raise.
    wiki_max_concurrency: int = 3
    # Seconds each worker waits between its own requests.
    wiki_throttle_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() is parsed once per process, not per request."""
    return Settings()
