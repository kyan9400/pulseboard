"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from ``PULSEBOARD_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="PULSEBOARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./pulseboard.db"
    api_key: str | None = None
    allow_private_targets: bool = False
    enable_scheduler: bool = True
    scheduler_tick_seconds: float = Field(default=5.0, gt=0, le=300)
    check_concurrency: int = Field(default=8, ge=1, le=100)
    max_checks_per_monitor: int = Field(default=1_000, ge=20, le=100_000)
    user_agent: str = "Pulseboard/1.0 (+https://github.com/kyan9400/pulseboard)"

    @property
    def show_docs(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
