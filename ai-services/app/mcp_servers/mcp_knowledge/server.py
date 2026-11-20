from app.knowledge.config import qdrant_url

from qdrant_client import AsyncQdrantClient

from app.configs import get_settings
from app.mcp_servers.mcp_knowledge.config import load_policy_config
from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
from app.mcp_servers.mcp_knowledge.services.knowledge import PolicySearchService
from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
from app.mcp_servers.mcp_shared.config import database_url, mcp_token
from app.mcp_servers.mcp_shared.observability import configure_mcp_logging


def main() -> None:
    settings = get_settings()
    configure_mcp_logging(settings.log_level)
    config = load_policy_config(settings)
    repo = PolicyRepository(
        database_url(settings), pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    client = AsyncQdrantClient(
        url=qdrant_url(),
        timeout=config.dependency_timeout_seconds,
    )
    service = PolicySearchService(
        repo, PolicyEncoder(config), HybridPolicyIndex(client), config,
    )
    create_server(service, mcp_token(settings)).run(
        transport='http', host=settings.mcp_host,
        port=settings.mcp_knowledge_port, path='/mcp',
    )


if __name__ == '__main__':
    main()
