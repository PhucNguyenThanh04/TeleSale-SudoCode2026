"""Async SQLAlchemy session lifecycle; repositories own every SQL statement."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Database:
    def __init__(self, dsn: str, pool_size: int = 5, max_overflow: int = 0) -> None:
        self.engine = create_async_engine(dsn, pool_pre_ping=True,
                                          pool_size=pool_size, max_overflow=max_overflow)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self):
        async with self.sessions() as session, session.begin():
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
