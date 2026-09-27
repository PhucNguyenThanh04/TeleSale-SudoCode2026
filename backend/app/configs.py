"""Backend configuration loaded from backend/.env and environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "TeleSale-SudoCode2026"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    timezone: str = "Asia/Ho_Chi_Minh"

    database_url: str
    redis_url: str
    ai_service_url: str
    ai_service_timeout_seconds: float = Field(default=30, gt=0)
    btc_data_dir: Path

    cors_origins: list[str] = Field(default_factory=list)

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
