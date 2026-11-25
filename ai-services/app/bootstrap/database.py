import asyncio

import asyncpg
from sqlalchemy.engine import make_url

from app.knowledge.config import configured_url


class BootError(ValueError):
    pass


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


async def pg_connect(dsn):
    deadline = asyncio.get_running_loop().time() + 30
    while True:
        try:
            return await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1), timeout=2)
        except (OSError, asyncpg.CannotConnectNowError):
            if asyncio.get_running_loop().time() >= deadline: raise
            await asyncio.sleep(0.2)


async def setup_store(dsn):
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from app.mcp_servers.mcp_memory.repos.langmem_projection import store_dsn
    async with AsyncPostgresStore.from_conn_string(store_dsn(dsn), index=None) as store:
        await store.setup()


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


async def setup_logins(conn, database, *, backend_dsn):
    for dsn, group in [(configured_url('KNOWLEDGE_DATABASE_URL'), 'knowledge_reviewer'),
                       (configured_url('KNOWLEDGE_WORKER_DATABASE_URL'), 'knowledge_worker'),
                       (backend_dsn, 'knowledge_backend')]:
        if not dsn: continue
        url = make_url(dsn)
        if not url.username: raise BootError('Application DB login is required')
        role = quoted(url.username)
        if not await conn.fetchval('SELECT 1 FROM pg_roles WHERE rolname=$1', url.username):
            if not url.password: raise BootError('A password is required to initialize an application DB login')
            sql = await conn.fetchval('SELECT format(\'CREATE ROLE %I LOGIN PASSWORD %L\', $1::text, $2::text)', url.username, url.password)
            await conn.execute(sql)
        if url.username != await conn.fetchval('SELECT current_user'):
            await conn.execute(f'GRANT {group} TO {role}')
        await conn.execute(f'GRANT CONNECT ON DATABASE {quoted(database)} TO {role}')
        await conn.execute(f'''GRANT USAGE ON SCHEMA system_boot TO {role};
            GRANT SELECT ON system_boot.current TO {role};''')
        if group == 'knowledge_backend':
            await conn.execute(f'''GRANT USAGE ON SCHEMA runtime,btc_source,system_boot TO {role};
                GRANT SELECT ON ALL TABLES IN SCHEMA btc_source TO {role};
                GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA runtime TO {role};
                GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA runtime TO {role};
                GRANT SELECT ON system_boot.current TO {role};''')
