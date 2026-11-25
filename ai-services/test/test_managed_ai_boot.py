import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def test_ai_waits_for_shared_schema_before_building_runtime(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'offline-key')
    monkeypatch.setenv('LLM_MODEL', 'offline-model')
    from app import main
    monkeypatch.setenv('SYSTEM_BOOT_ID', 'boot-1')
    monkeypatch.setattr(main, 'settings', SimpleNamespace(ai_internal_token=object(), log_level='INFO'))
    monkeypatch.setattr(main, 'configure_agent_logging', lambda _: None)
    runtime = Mock(side_effect=AssertionError('runtime cannot start before DB is ready'))
    monkeypatch.setattr(main, 'get_runtime', runtime)
    monkeypatch.setattr('app.bootstrap.database.require_ready', AsyncMock(side_effect=ValueError('boot not ready')))
    monkeypatch.setattr('app.mcp_servers.mcp_shared.config.database_url', lambda _: 'postgresql://offline')
    async def run():
        async with main.lifespan(SimpleNamespace(state=SimpleNamespace())):
            pytest.fail('must not accept requests')
    with pytest.raises(ValueError, match='not ready'): asyncio.run(run())
    runtime.assert_not_called()
