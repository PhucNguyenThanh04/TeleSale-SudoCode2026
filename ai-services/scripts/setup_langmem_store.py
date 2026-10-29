"""One-time admin setup for LangGraph's unqualified store DDL."""

import asyncio

from langgraph.store.postgres.aio import AsyncPostgresStore

from app.configs import get_settings
from app.mcp_servers.mcp_memory.repos.langmem_projection import store_dsn
from app.mcp_servers.mcp_shared.config import database_url


async def main() -> None:
    dsn = store_dsn(database_url(get_settings()))
    async with AsyncPostgresStore.from_conn_string(dsn, index=None) as store:
        await store.setup()


if __name__ == "__main__":
    asyncio.run(main())
