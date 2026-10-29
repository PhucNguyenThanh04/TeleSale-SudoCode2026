"""Complete an already verified memory erasure request across both stores."""

import asyncio
import sys

from app.configs import get_settings
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.services.erasure_executor import execute_erasure
from app.mcp_servers.mcp_shared.config import database_url


async def main(request_key: str) -> dict:
    dsn = database_url(get_settings())
    repo = MemoryRepo(dsn)
    try:
        return await execute_erasure(repo, request_key, LangMemProjection(dsn))
    finally:
        await repo.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.execute_memory_erasure REQUEST_UUID")
    result = asyncio.run(main(sys.argv[1]))
    print({"status": result.get("status", "error"),
           "store_statuses": {key: value.get("status") for key, value in
                              result.get("store_results", {}).items()}})
