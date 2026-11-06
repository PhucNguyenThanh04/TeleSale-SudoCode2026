from types import SimpleNamespace
import pytest
from pydantic import SecretStr
from app.mcp_servers.mcp_shared.config import database_url


@pytest.mark.parametrize('scheme', ['postgresql', 'postgres', 'postgresql+asyncpg'])
def test_database_url_uses_installed_async_driver_without_changing_credentials(scheme):
    settings = SimpleNamespace(database_url=SecretStr(f'{scheme}://user:p%40ss@localhost:5432/telesale'))
    assert database_url(settings) == 'postgresql+asyncpg://user:p%40ss@localhost:5432/telesale'
