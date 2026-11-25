import asyncio
from pathlib import Path
import shutil

from app.bootstrap.database import pg_connect, setup_logins, setup_store
from app.bootstrap.mcp_roles import provision
from app.bootstrap.policy import initialize_base
from dataloader_offline.postgres import import_release
from dataloader_offline.source import read_release, source_fingerprint
from dataloader_offline.verification import compare_source_tables
from eval_harness.seed_fingerprint import fingerprint_btc_source


BOOT_ID = 'btc-submission-v1'


def copy_policy_source(source, target):
    if target is not None and (source / 'policy').resolve() != target.resolve():
        shutil.copytree(source / 'policy', target, dirs_exist_ok=True)


async def prepare_policy(dsn, settings):
    import httpx
    from qdrant_client import AsyncQdrantClient
    from app.knowledge.config import qdrant_url
    from app.knowledge.policy.source import default_metadata
    from app.mcp_servers.mcp_knowledge.config import load_policy_config
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder

    repo = PolicyRepository(dsn)
    try:
        async with repo.transaction() as tx:
            active = await tx.get('active', 'current')
        if active:
            await repo.resolve_release()
            return
        url = qdrant_url()
        try:
            async with asyncio.timeout(30), httpx.AsyncClient(timeout=2) as client:
                while True:
                    try:
                        response = await client.get(f'{url.rstrip("/")}/readyz')
                        if response.is_success:
                            break
                    except httpx.RequestError:
                        pass
                    await asyncio.sleep(0.5)
        except TimeoutError:
            raise ValueError('Qdrant did not become ready during submission setup') from None
        config = load_policy_config(settings)
        encoder = PolicyEncoder(config)
        client = AsyncQdrantClient(url=url, timeout=config.dependency_timeout_seconds)
        try:
            async with repo.transaction() as tx:
                for actor in ('system-bootstrap', 'local-reviewer'):
                    await tx.put('permissions', actor, {'id': actor, 'permissions': ['knowledge_review']})
            await initialize_base(repo, encoder, HybridPolicyIndex(client),
                source_dir=settings.knowledge_policy_source_dir, metadata=default_metadata(),
                actor_id='system-bootstrap')
        finally:
            await encoder.close()
            await client.close()
    finally:
        await repo.close()


async def initialize(*, settings, dsn, expected_database, source, backend_dsn,
                     mcp_passwords, allow_policy_build=False):
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
                copy_policy_source(source, settings.knowledge_policy_source_dir)
                await provision(conn, mcp_passwords)
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
        await setup_logins(conn, expected_database, backend_dsn=backend_dsn)
        await provision(conn, mcp_passwords)
        copy_policy_source(source, settings.knowledge_policy_source_dir)
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
