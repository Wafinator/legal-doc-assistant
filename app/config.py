"""Application settings, loaded from environment variables (and a local .env file).

pydantic-settings maps each field to an env var of the same name, case-insensitive,
so `database_url` is read from DATABASE_URL. Values are validated and type-converted
on startup, so a typo like MAX_AGENT_STEPS=abc fails fast instead of at request time.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://legal:legal@localhost:5433/legal_docs"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once. Tests can call get_settings.cache_clear()."""
    return Settings()
