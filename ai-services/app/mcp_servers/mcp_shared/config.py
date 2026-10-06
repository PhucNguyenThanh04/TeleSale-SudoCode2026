"""Resolve validated MCP settings and container secrets."""

from pathlib import Path

from sqlalchemy.engine import URL
from app.configs import Settings


def secret(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Empty secret file: {path}")
    return value


def database_url(settings: Settings) -> str:
    if settings.database_url:
        return settings.database_url.get_secret_value()
    if not all((settings.mcp_db_user, settings.mcp_db_name, settings.mcp_db_password_file)):
        raise RuntimeError("DATABASE_URL or MCP_DB_PASSWORD_FILE is required")
    return URL.create("postgresql+asyncpg", username=settings.mcp_db_user,
        password=secret(settings.mcp_db_password_file), host=settings.mcp_db_host,
        port=settings.mcp_db_port,
        database=settings.mcp_db_name).render_as_string(hide_password=False)


def mcp_token(settings: Settings) -> str:
    token = (secret(settings.mcp_internal_token_file) if settings.mcp_internal_token_file
             else settings.mcp_internal_token.get_secret_value() if settings.mcp_internal_token else None)
    if not token:
        raise RuntimeError("MCP_INTERNAL_TOKEN is required")
    return token
