"""Centralized runtime settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Defaults are tuned for local development; production overrides
    must come from real environment variables, not `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="local")
    log_level: str = Field(default="INFO")

    mcp_server_url: str = Field(default="http://localhost:8001/mcp")
    mcp_timeout_seconds: float = Field(default=15.0, ge=0.1)
    mcp_max_retries: int = Field(default=2, ge=0, le=5)
    mcp_transport: str = Field(default="streamable_http")

    max_replan_attempts: int = Field(default=1, ge=0, le=3)

    use_mock_mcp: bool = Field(default=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
