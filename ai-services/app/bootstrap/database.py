"""One administrative boot transaction; application data never lives in btc_source."""
from pathlib import Path
import asyncio

import asyncpg


class BootError(ValueError):
    """Static startup diagnostics safe to show without database credentials."""


async def require_ready(dsn, boot_id):
    if not boot_id:
        return
    connection = await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1))
    try:
        current = await connection.fetchrow('SELECT boot_id,status FROM system_boot.current WHERE singleton')
        if not current or current['boot_id'] != boot_id or current['status'] != 'ready':
            raise BootError('Managed system boot is not ready or has been replaced')
    finally:
        await connection.close()


class BootDatabase:
    def __init__(self, dsn, expected_database, boot_id, *, app_env):
        self.dsn = dsn.replace('postgresql+asyncpg://', 'postgresql://', 1)
        self.expected_database, self.boot_id, self.app_env = expected_database, boot_id, app_env
        self.connection = None
        self.ready = False
        self.created = False

    async def __aenter__(self):
        if self.app_env == 'production' or not self.boot_id or not self.expected_database:
            raise BootError('Fresh startup requires a non-production environment, boot ID and explicit database')
        self.connection = await asyncpg.connect(self.dsn)
        try:
            if await self.connection.fetchval('SELECT current_database()') != self.expected_database:
                raise BootError('Startup database does not match expected database')
            # A blocking SELECT holds a snapshot and deadlocks concurrent store indexes.
            while not await self.connection.fetchval('SELECT pg_try_advisory_lock(714222, 1)'):
                await asyncio.sleep(0.1)
            if not await self.connection.fetchval("SELECT to_regclass('btc_source.customers')"):
                raise BootError('Import BTC source first; startup never invents source customers')
            await self.connection.execute('''CREATE SCHEMA IF NOT EXISTS system_boot;
                CREATE TABLE IF NOT EXISTS system_boot.current (
                    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                    boot_id text NOT NULL, status text NOT NULL,
                    started_at timestamptz NOT NULL DEFAULT now())''')
            current = await self.connection.fetchrow('SELECT boot_id,status FROM system_boot.current WHERE singleton')
            self.ready = bool(current and current['boot_id'] == self.boot_id and current['status'] == 'ready')
            return self
        except BaseException:
            await self.connection.close()
            raise

    async def create_fresh_schema(self):
        if self.ready:
            return
        async with self.connection.transaction():
            await self.connection.execute('''INSERT INTO system_boot.current(singleton,boot_id,status)
                VALUES(true,$1,$2) ON CONFLICT(singleton) DO UPDATE
                SET boot_id=EXCLUDED.boot_id,status=EXCLUDED.status,started_at=now()''', self.boot_id, 'starting')
            await self.connection.execute('''DROP SCHEMA IF EXISTS knowledge CASCADE;
                DROP SCHEMA IF EXISTS runtime CASCADE;
                DROP SCHEMA IF EXISTS app_runtime CASCADE;
                DROP SCHEMA IF EXISTS ai_memory CASCADE;
                DROP SCHEMA IF EXISTS langmem_store CASCADE;''')
            await self.connection.execute(Path(__file__).with_name('schema.sql').read_text())
        self.created = True

    async def mark_ready(self):
        if not self.ready and not self.created:
            raise BootError('Cannot publish a boot before creating its schema')
        await self.connection.execute('''INSERT INTO system_boot.current(singleton,boot_id,status)
            VALUES(true,$1,$2) ON CONFLICT(singleton) DO UPDATE SET status=EXCLUDED.status''', self.boot_id, 'ready')
        self.ready = True

    async def __aexit__(self, *exc):
        await self.connection.close()  # Releases the session advisory lock, including on failures.
