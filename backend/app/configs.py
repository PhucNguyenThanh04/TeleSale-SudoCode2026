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
    ai_internal_token: SecretStr | None = None
    btc_data_dir: Path

    cors_origins: list[str] = Field(default_factory=list)

@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()


class VoiceSettings(BaseSettings):
    """Standalone voice gateway does not require database/operator settings."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore", case_sensitive=False,
    )

    ai_service_url: str = "http://127.0.0.1:8001"
    ai_service_timeout_seconds: float = Field(default=120, gt=0)
    ai_internal_token: SecretStr | None = None
    knowledge_review_token: SecretStr | None = None
    knowledge_reviewer_id: str = ''
    speech_http_url: str = "http://127.0.0.1:18110"
    speech_listen_url: str = "ws://127.0.0.1:18110/v1/speech/listen"
    speech_voice: str = "Trúc Ly"
    speech_connect_timeout_seconds: float = Field(default=10, gt=0)
    speech_timeout_seconds: float = Field(default=120, gt=0)
    voice_start_timeout_seconds: float = Field(default=10, gt=0)
