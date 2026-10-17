"""AI service settings loaded from ai-services/.env and process environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS



_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "TeleSale AI Service"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    timezone: str = "Asia/Ho_Chi_Minh"

    llm_api_key: SecretStr = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    ollama_base_url: AnyHttpUrl = "https://ollama.com"
    ollama_timeout_seconds: float = Field(default=30, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=1)
    llm_max_tokens: int = Field(default=256, ge=1)
    agent_max_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=3, le=20)
    agent_prompt_history_turns: int = Field(default=DEFAULT_PROMPT_HISTORY_TURNS, ge=1, le=12)
    agent_guardrails_enabled: bool = True
    agent_kind: Literal["deep", "react"] = "deep"
    fact_extraction_mode: Literal["fallback", "always", "off"] = "fallback"
    langfuse_enabled: bool = False
    langfuse_capture_content: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: AnyHttpUrl | None = None
    memory_max_episodes: int = Field(default=5, ge=0, le=20)
    memory_summary_turns: int = Field(default=3, ge=1, le=20)
    memory_summary_max_chars: int = Field(default=800, ge=100, le=800)
    ai_internal_token: SecretStr | None = None
    mcp_internal_token: SecretStr | None = None
    mcp_internal_token_file: Path | None = None
    database_url: SecretStr | None = None
    mcp_host: str = "127.0.0.1"
    mcp_catalog_port: int = Field(default=8011, ge=1, le=65535)
    mcp_order_port: int = Field(default=8012, ge=1, le=65535)
    mcp_memory_port: int = Field(default=8013, ge=1, le=65535)
    mcp_catalog_url: str | None = None
    mcp_order_url: str | None = None
    mcp_memory_url: str | None = None
    mcp_db_host: str = "postgres"
    mcp_db_port: int = Field(default=5432, ge=1, le=65535)
    mcp_db_name: str | None = None
    mcp_db_user: str | None = None
    mcp_db_password_file: Path | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=0, ge=0, le=50)
    memory_db_pool_min_size: int = Field(default=1, ge=1, le=50)
    memory_db_pool_max_size: int = Field(default=5, ge=1, le=50)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("TIMEZONE must be a valid IANA time zone") from exc
        return value

    @model_validator(mode="after")
    def validate_pool_range(self) -> "Settings":
        if self.memory_db_pool_min_size > self.memory_db_pool_max_size:
            raise ValueError("MEMORY_DB_POOL_MIN_SIZE must not exceed MEMORY_DB_POOL_MAX_SIZE")
        if self.langfuse_enabled and not all((self.langfuse_public_key,
                                              self.langfuse_secret_key,
                                              self.langfuse_base_url)):
            raise ValueError("LANGFUSE_ENABLED requires public key, secret key and base URL")
        if self.langfuse_capture_content and self.app_env == "production":
            raise ValueError("LANGFUSE_CAPTURE_CONTENT cannot be enabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
