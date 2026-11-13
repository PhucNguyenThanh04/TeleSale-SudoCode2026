"""Gateway waits for its generation; it never resets the shared DB itself."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.configs import VoiceSettings
from app.voice_main import create_app


@pytest.mark.parametrize('boot', [None, {'boot_id': 'old', 'status': 'ready'}, {'boot_id': 'new', 'status': 'ready'}])
def test_gateway_rejects_wrong_generation_and_closes_pool(monkeypatch, boot):
    conn = SimpleNamespace(fetchrow=AsyncMock(return_value=boot))
    @asynccontextmanager
    async def acquire():
        yield conn
    pool = SimpleNamespace(acquire=acquire, close=AsyncMock())
    monkeypatch.setenv('SYSTEM_BOOT_ID', 'new')
    monkeypatch.setattr('app.voice_main.asyncpg.create_pool', AsyncMock(return_value=pool))
    app = create_app(VoiceSettings(_env_file=None, database_url='postgresql://u:pw@localhost/test'))
    async def run():
        async with app.router.lifespan_context(app):
            assert app.state.demo_users is not None
    if not boot or boot['boot_id'] != 'new':
        with pytest.raises(RuntimeError, match='boot'): asyncio.run(run())
    else:
        asyncio.run(run())
    pool.close.assert_awaited_once()
    assert 'SELECT boot_id,status' in conn.fetchrow.call_args.args[0]
