"""PostgreSQL engine and request-scoped SQLAlchemy sessions."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_pg_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_pg_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_postgres(engine: AsyncEngine) -> None:
    """Fail startup promptly if PostgreSQL is unavailable."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_pg_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency; closes each session after its request."""
    async with request.app.state.pg_sessionmaker() as session:
        yield session
