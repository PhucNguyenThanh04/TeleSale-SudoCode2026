import asyncio
from unittest.mock import AsyncMock

import asyncpg
import pytest

from scripts import btc_container


def test_servers_wait_for_seed_and_close_probe_connections(monkeypatch):
    missing = AsyncMock()
    missing.fetchval.return_value = None
    starting = AsyncMock()
    starting.fetchval.return_value = True
    starting.fetchrow.return_value = {'boot_id': 'boot-1', 'status': 'starting'}
    ready = AsyncMock()
    ready.fetchval.return_value = True
    ready.fetchrow.return_value = {'boot_id': 'boot-1', 'status': 'ready'}
    connect = AsyncMock(side_effect=[asyncpg.InvalidAuthorizationSpecificationError('not seeded'),
                                    missing, starting, ready])
    sleep = AsyncMock()
    monkeypatch.setattr(asyncpg, 'connect', connect)
    monkeypatch.setattr(btc_container.asyncio, 'sleep', sleep)
    asyncio.run(btc_container.wait_for_seed('postgresql+asyncpg://test', 'boot-1'))
    assert connect.await_count == 4
    assert sleep.await_count == 3
    for connection in (missing, starting, ready):
        connection.close.assert_awaited_once()


def test_seed_wait_rejects_a_different_managed_database(monkeypatch):
    connection = AsyncMock()
    connection.fetchval.return_value = True
    connection.fetchrow.return_value = {'boot_id': 'another-boot', 'status': 'ready'}
    monkeypatch.setattr(asyncpg, 'connect', AsyncMock(return_value=connection))
    with pytest.raises(ValueError, match='different managed startup'):
        asyncio.run(btc_container.wait_for_seed('postgresql://test', 'boot-1'))
    connection.close.assert_awaited_once()


@pytest.mark.parametrize('mode,role', [('ai', 'btc_reviewer'), ('backend', 'btc_backend'),
                                     ('worker', 'btc_worker')])
def test_application_waits_using_its_database_role(monkeypatch, mode, role):
    wait = AsyncMock()
    commands = []
    monkeypatch.setattr(btc_container, 'secret', lambda _: 'abc123')
    monkeypatch.setattr(btc_container, 'wait_for_seed', wait)
    monkeypatch.setattr(btc_container.sys, 'argv', ['btc_container.py', mode, 'python', '-m', 'app'])
    monkeypatch.setattr(btc_container.os, 'execvp', lambda *args: commands.append(args))
    monkeypatch.setenv('MCP_DB_NAME', 'telesale_eval_m1')
    monkeypatch.setenv('SYSTEM_BOOT_ID', 'boot-1')
    monkeypatch.setenv('SUBMISSION_WAIT_FOR_SEED', '1')
    btc_container.main()
    assert f'{role}:' in wait.call_args.args[0]
    assert wait.call_args.args[1] == 'boot-1'
    assert commands == [('python', ['python', '-m', 'app'])]
