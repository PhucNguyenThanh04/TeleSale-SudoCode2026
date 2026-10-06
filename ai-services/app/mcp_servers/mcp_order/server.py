"""mcp-order process entrypoint."""

from app.configs import get_settings
from app.mcp_servers.mcp_order.repos.postgres import OrderRepo
from app.mcp_servers.mcp_order.tools.handlers import create_server
from app.mcp_servers.mcp_shared.config import database_url, mcp_token
from app.mcp_servers.mcp_shared.observability import configure_mcp_logging


def main() -> None:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    repo = OrderRepo(database_url(settings), pool_size=settings.db_pool_size,
                     max_overflow=settings.db_max_overflow)
    token = mcp_token(settings)
    create_server(repo, token).run(transport="http", host=settings.mcp_host,
                                   port=settings.mcp_order_port, path="/mcp")


if __name__ == "__main__":
    main()
