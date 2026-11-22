import argparse
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

from app.configs import get_settings
from app.mcp_servers.mcp_shared.config import database_url
from app.system_start import fingerprint_btc_source, pg_connect, setup_logins, setup_policy, setup_store
from dataloader_offline.postgres import import_release
from dataloader_offline.source import read_release, source_fingerprint
from dataloader_offline.verification import compare_source_tables


BOOT_ID = 'btc-submission-v1'


async def prepare_policy(dsn, settings):
    import httpx
    from app.knowledge.config import qdrant_url
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository

    repo = PolicyRepository(dsn)
    try:
        async with repo.transaction() as tx:
            active = await tx.get('active', 'current')
        if active:
            await repo.resolve_release()
            return
    finally:
        await repo.close()
    try:
        async with asyncio.timeout(30), httpx.AsyncClient(timeout=2) as client:
            while True:
                try:
                    response = await client.get(f'{qdrant_url().rstrip("/")}/readyz')
                    if response.is_success:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.5)
    except TimeoutError:
        raise ValueError('Qdrant did not become ready during submission setup') from None
    await setup_policy(dsn, settings, None, [])


async def initialize(*, settings, dsn, expected_database, source, backend_dsn, allow_policy_build=False):
    if settings.app_env == 'production':
        raise ValueError('Submission setup requires a dedicated non-production database')
    source_hash = source_fingerprint(source)
    conn = await pg_connect(dsn)
    try:
        if await conn.fetchval('SELECT current_database()') != expected_database:
            raise ValueError('Connected database differs from the submission database')
        await conn.execute('SELECT pg_advisory_lock(714222, 1)')
        state = None
        if await conn.fetchval("SELECT to_regclass('system_boot.submission')"):
            state = await conn.fetchrow(
                'SELECT source_hash, db_hash, status FROM system_boot.submission WHERE singleton')
        if state:
            if state['source_hash'] != source_hash:
                raise ValueError('BTC source differs from the initialized database. Use a new submission project.')
            if state['db_hash'] != await fingerprint_btc_source(dsn):
                raise ValueError('Stored BTC data differs from the initialized snapshot')
            if state['status'] == 'ready':
                return 'already_initialized'
        elif await conn.fetchval("""SELECT EXISTS (
            SELECT 1 FROM pg_namespace WHERE nspname IN
                ('runtime','knowledge','system_boot','app_runtime','ai_memory','langmem_store'))"""):
            raise ValueError('Existing operational schema belongs to another deployment. Use a new submission project.')
        if not allow_policy_build:
            raise ValueError('First setup requires --allow-policy-build to prepare the policy index')
        if not state:
            release = read_release(source)
            if await conn.fetchval("SELECT to_regnamespace('btc_source')"):
                comparisons = await compare_source_tables(conn, release)
                if any(row['missing'] or row['extra'] or row['changed'] for row in comparisons.values()):
                    raise ValueError('Existing BTC source differs from the input. Use a new submission project.')
            else:
                await import_release(dsn, release)
            db_hash = await fingerprint_btc_source(dsn)
            async with conn.transaction():
                await conn.execute(Path(__file__).with_name('schema.sql').read_text())
                await conn.execute('''CREATE SCHEMA system_boot;
                    CREATE TABLE system_boot.current (
                        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                        boot_id text NOT NULL, status text NOT NULL,
                        started_at timestamptz NOT NULL DEFAULT now());
                    CREATE TABLE system_boot.submission (
                        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                        source_hash text NOT NULL, db_hash text NOT NULL, status text NOT NULL
                    )''')
                await conn.execute("""INSERT INTO system_boot.submission(singleton,source_hash,db_hash,status)
                    VALUES(true,$1,$2,'starting')""", source_hash, db_hash)
                await conn.execute("""INSERT INTO system_boot.current(singleton,boot_id,status)
                    VALUES(true,$1,'starting')""", BOOT_ID)
        await setup_store(dsn)
        await setup_logins(SimpleNamespace(connection=conn, expected_database=expected_database),
                           settings, backend_dsn=backend_dsn)
        await prepare_policy(dsn, settings)
        async with conn.transaction():
            await conn.execute("""UPDATE system_boot.submission SET status='ready' WHERE singleton;
                UPDATE system_boot.current SET status='ready' WHERE singleton""")
        return 'initialized'
    finally:
        await conn.close()


async def verify_source(dsn, source):
    conn = await pg_connect(dsn)
    try:
        state = await conn.fetchrow(
            'SELECT source_hash, db_hash, status FROM system_boot.submission WHERE singleton')
        if not state or state['status'] != 'ready':
            raise ValueError('Submission database is not initialized')
        if (state['source_hash'] != source_fingerprint(source)
                or state['db_hash'] != await fingerprint_btc_source(dsn)):
            raise ValueError('Eval BTC source differs from the initialized database')
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description='Initialize a dedicated BTC submission database')
    parser.add_argument('--allow-policy-build', action='store_true')
    args = parser.parse_args()
    settings = get_settings()
    try:
        result = asyncio.run(initialize(settings=settings, dsn=database_url(settings),
            expected_database=os.environ['MCP_DB_NAME'], source=Path(os.environ['BTC_DATA_DIR']),
            backend_dsn=os.environ['BTC_BACKEND_DATABASE_URL'], allow_policy_build=args.allow_policy_build))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Submission setup failed: {exc}\n')
    print(f'BTC submission setup: {result}')


if __name__ == '__main__':
    main()
