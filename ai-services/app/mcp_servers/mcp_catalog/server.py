"""mcp-catalog process entrypoint."""

from app.configs import get_settings
from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
from app.mcp_servers.mcp_catalog.tools.handlers import create_server
from app.mcp_servers.mcp_shared.config import database_url, mcp_token
from app.mcp_servers.mcp_shared.observability import configure_mcp_logging


def main() -> None:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    repo = CatalogRepo(database_url(settings), pool_size=settings.db_pool_size,
                       max_overflow=settings.db_max_overflow)
    token = mcp_token(settings)
    create_server(repo, token).run(transport="http", host=settings.mcp_host,
                                   port=settings.mcp_catalog_port, path="/mcp")


if __name__ == "__main__":
    main()
