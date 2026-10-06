"""mcp-memory process entrypoint."""

from app.configs import get_settings
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.tools.handlers import create_server
from app.mcp_servers.mcp_shared.config import database_url, mcp_token
from app.mcp_servers.mcp_shared.observability import configure_mcp_logging


def main() -> None:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    repo = MemoryRepo(database_url(settings), min_size=settings.memory_db_pool_min_size,
                      max_size=settings.memory_db_pool_max_size)
    token = mcp_token(settings)
    create_server(repo, token).run(transport="http", host=settings.mcp_host,
                                   port=settings.mcp_memory_port, path="/mcp")


if __name__ == "__main__":
    main()
