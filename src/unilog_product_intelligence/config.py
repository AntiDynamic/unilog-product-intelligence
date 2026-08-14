"""Application configuration and environment-variable contracts."""

from functools import lru_cache
from typing import Final

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GEMINI_MODEL: Final[str] = "gemini-3.5-flash-lite"


class Settings(BaseSettings):
    """Validated runtime settings.

    Secrets are loaded from the environment or a local, Git-ignored ``.env`` file.
    The secret is deliberately represented as ``SecretStr`` so accidental logging is
    less likely to disclose it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "unilog-product-intelligence"
    environment: str = "development"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = GEMINI_MODEL
    live_external_execution: bool = False
    database_url: str = "postgresql+psycopg://localhost/unilog"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()
