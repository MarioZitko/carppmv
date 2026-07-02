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


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() is parsed once per process, not per request."""
    return Settings()