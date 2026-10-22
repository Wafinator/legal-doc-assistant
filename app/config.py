"""Application settings, loaded from environment variables (and a local .env file).

pydantic-settings maps each field to an env var of the same name, case-insensitive,
so `database_url` is read from DATABASE_URL. Values are validated and type-converted
on startup, so a typo like LLM_MAX_ATTEMPTS=abc fails fast instead of at request time.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://legal:legal@localhost:5433/legal_docs"
    log_level: str = "INFO"

    # SecretStr hides the value in repr() and logs: printing settings shows '**********'.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-5-5"
    # Effort is Haiku 5.5's main cost lever: "low" means less thinking and fewer tokens.
    llm_effort: str = "low"
    # Thinking tokens count toward this cap, so leave headroom above the answer length.
    llm_max_tokens: int = 8000

    # Timeouts in seconds. On a stream, the read timeout is the longest allowed
    # gap between two chunks, not the total length of the response.
    llm_connect_timeout: float = 5.0
    llm_read_timeout: float = 30.0

    # Total tries per LLM call, including the first one.
    llm_max_attempts: int = 3
    llm_retry_base_delay: float = 0.5
    llm_retry_max_delay: float = 8.0


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once. Tests can call get_settings.cache_clear()."""
    return Settings()
