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

    llm_backend: Literal["api", "local"] = "api"
    local_llm_api_key: SecretStr = Field(default="local-vllm", min_length=1)
    local_llm_model: str = Field(default="Qwen/Qwen2.5-3B-Instruct-AWQ", min_length=1)
    local_llm_base_url: AnyHttpUrl = "http://localhost:8081/v1"
    local_llm_context_window: int = Field(default=8192, ge=256)
    local_llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_api_key: SecretStr = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    llm_base_url: AnyHttpUrl = "https://api.openai.com/v1"
    llm_timeout_seconds: float = Field(default=30, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=1)
    llm_max_tokens: int = Field(default=256, ge=1)
    llm_seed: int | None = None
    agent_max_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=3, le=20)
    agent_prompt_history_turns: int = Field(default=DEFAULT_PROMPT_HISTORY_TURNS, ge=1, le=12)
    agent_guardrails_enabled: bool = True
    agent_kind: Literal["deep", "react"] = "deep"
    langmem_model: str | None = None
    langmem_max_tokens: int = Field(default=1024, ge=256, le=8192)
    langfuse_enabled: bool = False
    langfuse_prompts_enabled: bool = False
    langfuse_capture_content: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: AnyHttpUrl | None = None
    knowledge_enabled: bool = False
    knowledge_database_url: SecretStr | None = None
    knowledge_worker_database_url: SecretStr | None = None
    knowledge_admin_database_url: SecretStr | None = None
    knowledge_release_id: str | None = None
    memory_max_episodes: int = Field(default=5, ge=0, le=20)
    ai_internal_token: SecretStr | None = None
    mcp_internal_token: SecretStr | None = None
    mcp_internal_token_file: Path | None = None
    database_url: SecretStr | None = None
    mcp_host: str = "127.0.0.1"
    mcp_catalog_port: int = Field(default=8011, ge=1, le=65535)
    mcp_order_port: int = Field(default=8012, ge=1, le=65535)
    mcp_memory_port: int = Field(default=8013, ge=1, le=65535)
    mcp_knowledge_port: int = Field(default=8014, ge=1, le=65535)
    mcp_knowledge_url: str | None = None
    knowledge_policy_config_file: Path | None = None
    knowledge_policy_source_dir: Path | None = None
    cloudflare_account_id: str | None = None
    cloudflare_api_token: SecretStr | None = None
    qdrant_url: str = 'http://127.0.0.1:6333'
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

    @model_validator(mode="before")
    @classmethod
    def select_llm_backend(cls, values):
        """Resolve the active connection without editing the API profile on disk."""
        if isinstance(values, dict) and values.get("llm_backend") == "local":
            values = dict(values)
            for field in ("llm_api_key", "llm_model", "llm_base_url"):
                local_field = f"local_{field}"
                values[field] = values.get(local_field, cls.model_fields[local_field].default)
            # A cloud-only LANGMEM_MODEL must never be sent to the local server.
            values["langmem_model"] = values["llm_model"]
        return values

    @field_validator("langfuse_base_url", mode="before")
    @classmethod
    def normalize_optional_langfuse_url(cls, value):
        """Compose supplies empty strings for unset optional environment values."""
        return None if isinstance(value, str) and not value.strip() else value

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
        if (self.langfuse_enabled or self.langfuse_prompts_enabled) and not all((self.langfuse_public_key,
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
