import asyncio
from unittest.mock import AsyncMock

import pytest

from app.bootstrap.database import BootError, require_ready


@pytest.mark.parametrize('current', [None, {'boot_id': 'old', 'status': 'ready'},
                                     {'boot_id': 'new', 'status': 'starting'}])
def test_server_rejects_stale_or_partial_boot(monkeypatch, current):
    connection = AsyncMock()
    connection.fetchrow.return_value = current
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    with pytest.raises(BootError):
        asyncio.run(require_ready('postgresql://offline', 'new'))
    connection.close.assert_awaited_once()
