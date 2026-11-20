import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


class Connection:
    def __init__(self, current=None):
        self.current = current
        self.statements = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        if 'INSERT INTO system_boot.current' in sql:
            self.current = {'boot_id': args[0], 'status': args[1]}

    async def fetchval(self, sql, *args):
        if 'pg_try_advisory_lock' in sql: return True
        if 'current_database()' in sql: return 'telesale'
        if "to_regclass('btc_source.customers')" in sql: return 'btc_source.customers'

    async def fetchrow(self, sql, *args):
        return self.current

    async def close(self):
        pass


def test_fresh_boot_clears_runtime_and_all_knowledge_without_touching_btc(monkeypatch):
    from app.bootstrap.database import BootDatabase
    connection = Connection()
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    async def run():
        async with BootDatabase('postgresql://offline', 'telesale', 'boot-1', app_env='test') as boot:
            assert not boot.ready
            await boot.create_fresh_schema()
            await boot.mark_ready()
    asyncio.run(run())
    sql = '\n'.join(s for s, _ in connection.statements)
    assert 'DROP SCHEMA IF EXISTS runtime CASCADE' in sql
    assert 'DROP SCHEMA IF EXISTS knowledge CASCADE' in sql
    assert 'DROP SCHEMA IF EXISTS btc_source' not in sql
    assert 'TRUNCATE btc_source' not in sql
    assert 'CREATE TABLE IF NOT EXISTS runtime.demo_users' in sql
    assert 'CREATE TABLE IF NOT EXISTS knowledge.permissions' in sql
    assert 'CREATE TABLE IF NOT EXISTS knowledge.active' in sql
    assert connection.current == {'boot_id': 'boot-1', 'status': 'ready'}


def test_same_boot_id_cannot_reset_again(monkeypatch):
    from app.bootstrap.database import BootDatabase
    connection = Connection({'boot_id': 'boot-1', 'status': 'ready'})
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    async def run():
        async with BootDatabase('postgresql://offline', 'telesale', 'boot-1', app_env='test') as boot:
            assert boot.ready
            await boot.create_fresh_schema()
    asyncio.run(run())
    assert not any('DROP SCHEMA' in sql for sql, _ in connection.statements)


@pytest.mark.parametrize('app_env,expected', [('production', 'telesale'), ('test', 'wrong_database')])
def test_bad_environment_or_target_fails_before_reset(monkeypatch, app_env, expected):
    from app.bootstrap.database import BootDatabase
    connection = Connection()
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    async def run():
        async with BootDatabase('postgresql://offline', expected, 'boot-1', app_env=app_env):
            pytest.fail('must refuse')
    with pytest.raises(ValueError): asyncio.run(run())
    assert not any('DROP SCHEMA' in sql for sql, _ in connection.statements)


def test_failed_initialization_never_sets_ready(monkeypatch):
    from app.bootstrap.database import BootDatabase
    connection = Connection()
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    async def run():
        async with BootDatabase('postgresql://offline', 'telesale', 'boot-1', app_env='test') as boot:
            await boot.create_fresh_schema()
            raise RuntimeError('index unavailable')
    with pytest.raises(RuntimeError): asyncio.run(run())
    assert connection.current['status'] != 'ready'


@pytest.mark.parametrize('current', [None, {'boot_id': 'old', 'status': 'ready'}, {'boot_id': 'new', 'status': 'starting'}])
def test_server_cannot_accept_stale_or_partial_boot(monkeypatch, current):
    from app.bootstrap.database import require_ready
    connection = Connection(current)
    monkeypatch.setattr('app.bootstrap.database.asyncpg.connect', AsyncMock(return_value=connection))
    with pytest.raises(ValueError): asyncio.run(require_ready('postgresql://offline', 'new'))
    assert not any('DROP' in sql or 'INSERT' in sql for sql, _ in connection.statements)
