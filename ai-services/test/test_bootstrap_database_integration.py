import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app.bootstrap.database import BootDatabase
from app.system_start import setup_store
from eval_harness.seed_fingerprint import fingerprint_btc_source


def test_fresh_schema_and_concurrent_boots_preserve_btc_source(monkeypatch):
    admin_dsn = os.getenv('BOOTSTRAP_INTEGRATION_ADMIN_DSN')
    if not admin_dsn: pytest.skip('BOOTSTRAP_INTEGRATION_ADMIN_DSN required for temporary DB test')
    async def run():
        admin = await asyncpg.connect(admin_dsn.replace('postgresql+asyncpg://', 'postgresql://', 1))
        name = 'tele_bootstrap_test_' + uuid4().hex[:12]
        dsn = make_url(admin_dsn).set(database=name).render_as_string(hide_password=False)
        managed_roles = {'knowledge_worker', 'knowledge_reviewer', 'knowledge_ingest', 'knowledge_backend', 'mcp_knowledge'}
        login_names = {kind: name + '_' + kind for kind in ('reviewer', 'worker', 'backend')}
        role_dsns = {kind: make_url(dsn).set(username=user, password='temporary-test-password').render_as_string(hide_password=False)
                     for kind, user in login_names.items()}
        from app import system_start
        monkeypatch.setattr(system_start, 'configured_url', lambda key: role_dsns[
            'worker' if key == 'KNOWLEDGE_WORKER_DATABASE_URL' else 'reviewer'])
        monkeypatch.setattr(system_start, 'backend_values', lambda: {'DATABASE_URL': role_dsns['backend']})
        existing = {r['rolname'] for r in await admin.fetch('SELECT rolname FROM pg_roles')}
        await admin.execute(f'CREATE DATABASE "{name}"')
        try:
            conn = await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1))
            try:
                await conn.execute('''CREATE SCHEMA btc_source;
                    CREATE TABLE btc_source.customers(customer_id text PRIMARY KEY, name text);
                    INSERT INTO btc_source.customers VALUES('SOURCE-CUSTOMER','Original BTC fixture');
                    CREATE TABLE btc_source.policy_chunks(chunk_id text PRIMARY KEY, body text);
                    INSERT INTO btc_source.policy_chunks VALUES('SOURCE-POLICY','Original policy');''')
            finally: await conn.close()
            before = await fingerprint_btc_source(dsn)
            async with BootDatabase(dsn, name, 'first', app_env='test') as boot:
                await boot.create_fresh_schema()
                await setup_store(dsn)
                await system_start.setup_logins(boot, None)
                for kind, value in role_dsns.items():
                    client = await asyncpg.connect(value.replace('postgresql+asyncpg://', 'postgresql://', 1))
                    try:
                        assert await client.fetchval('SELECT status FROM system_boot.current') == 'starting'
                        if kind == 'worker':
                            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                                await client.execute("INSERT INTO knowledge.active(id,data) VALUES('forbidden','{}')")
                    finally: await client.close()
                await boot.connection.execute('''INSERT INTO runtime.demo_users(id,username,password_hash,customer_id)
                    VALUES('old-user','old-user','test-hash','SOURCE-CUSTOMER');
                    INSERT INTO runtime.turns(session_id,turn_no,channel,on_date,customer_text,agent_text)
                    VALUES('11111111-1111-4111-8111-111111111111',1,'hotline','2026-11-13','old','old');''')
                tables = await boot.connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='knowledge'")
                for r in tables:
                    await boot.connection.execute(f'INSERT INTO knowledge."{r["tablename"]}"(id,data) VALUES($1,$2::jsonb)', 'old', '{}')
                await boot.mark_ready()
            async with BootDatabase(dsn, name, 'first', app_env='test') as boot:
                assert boot.ready
                await boot.create_fresh_schema()
                assert await boot.connection.fetchval('SELECT count(*) FROM runtime.demo_users') == 1
            initialized = []
            async def next_boot():
                async with BootDatabase(dsn, name, 'second', app_env='test') as boot:
                    if not boot.ready:
                        initialized.append('created')
                        await boot.create_fresh_schema(); await setup_store(dsn); await boot.mark_ready()
            await asyncio.wait_for(asyncio.gather(next_boot(), next_boot()), timeout=30)
            assert initialized == ['created']
            conn = await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1))
            try:
                tables = await conn.fetch("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('runtime','knowledge')")
                for r in tables:
                    if r['tablename'] == 'store_migrations': continue
                    assert await conn.fetchval(f'SELECT count(*) FROM "{r["schemaname"]}"."{r["tablename"]}"') == 0
                assert await conn.fetchval('SELECT count(*) FROM system_boot.current') == 1
            finally: await conn.close()
            assert await fingerprint_btc_source(dsn) == before
        finally:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            for user in login_names.values():
                await admin.execute(f'DROP ROLE IF EXISTS "{user}"')
            for role in managed_roles - existing:
                await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
            await admin.close()
    asyncio.run(run())
