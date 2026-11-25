import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_submission_setup_preserves_ready_database_and_rejects_source_change(monkeypatch, tmp_path):
    from app.bootstrap import submission

    class Connection:
        source = None
        status = None
        runtime = False
        has_btc_source = False

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def fetchval(self, sql):
            if 'current_database' in sql:
                return 'telesale_eval_m1'
            if 'to_regclass' in sql:
                return self.source is not None
            if 'to_regnamespace' in sql:
                return self.has_btc_source
            if 'pg_namespace' in sql:
                return self.runtime
            if 'current_user' in sql:
                return 'admin'
            return None

        async def fetchrow(self, sql):
            return {'source_hash': self.source, 'db_hash': 'db-digest', 'status': self.status}

        async def execute(self, sql, *args):
            assert 'DROP SCHEMA' not in sql
            if 'INSERT INTO system_boot.submission' in sql:
                self.source = args[0]
                self.status = 'starting'
                self.runtime = True
            if "status='ready'" in sql:
                self.status = 'ready'

        async def close(self):
            pass

    conn = Connection()
    importer, install, policy = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(submission, 'pg_connect', AsyncMock(return_value=conn))
    monkeypatch.setattr(submission, 'source_fingerprint', lambda path: path.name)
    monkeypatch.setattr(submission, 'read_release', lambda _: {})
    monkeypatch.setattr(submission, 'import_release', importer)
    monkeypatch.setattr(submission, 'fingerprint_btc_source', AsyncMock(return_value='db-digest'))
    monkeypatch.setattr(submission, 'setup_store', install)
    monkeypatch.setattr(submission, 'setup_logins', AsyncMock())
    monkeypatch.setattr(submission, 'prepare_policy', policy)
    provision = AsyncMock()
    monkeypatch.setattr(submission, 'provision', provision, raising=False)
    source_policy = tmp_path / 'first' / 'policy'
    source_policy.mkdir(parents=True)
    (source_policy / 'policy.md').write_text('original policy')
    settings = SimpleNamespace(app_env='test', knowledge_policy_source_dir=tmp_path / 'runtime-policy')
    kwargs = dict(settings=settings, dsn='test', expected_database='telesale_eval_m1',
                  source=tmp_path / 'first', backend_dsn='postgresql://backend@postgres/test',
                  mcp_passwords={name: 'abc123' for name in ('catalog', 'order', 'memory', 'knowledge')})

    with pytest.raises(ValueError, match='allow-policy-build'):
        asyncio.run(submission.initialize(**kwargs))
    assert not conn.runtime

    conn.has_btc_source = True
    compare = AsyncMock(return_value={'products': {'missing': [], 'changed': ['sku'], 'extra': []}})
    monkeypatch.setattr(submission, 'compare_source_tables', compare, raising=False)
    with pytest.raises(ValueError, match='Existing BTC source differs'):
        asyncio.run(submission.initialize(**kwargs, allow_policy_build=True))
    importer.assert_not_awaited()
    conn.has_btc_source = False

    provision.side_effect = RuntimeError('roles unavailable')
    with pytest.raises(RuntimeError, match='roles unavailable'):
        asyncio.run(submission.initialize(**kwargs, allow_policy_build=True))
    assert conn.status == 'starting'
    provision.side_effect = None
    asyncio.run(submission.initialize(**kwargs, allow_policy_build=True))
    staged_policy = settings.knowledge_policy_source_dir / 'policy.md'
    assert staged_policy.read_text() == 'original policy'
    staged_policy.unlink()
    asyncio.run(submission.initialize(**kwargs))
    assert staged_policy.read_text() == 'original policy'
    assert conn.status == 'ready'
    importer.assert_awaited_once()
    assert install.await_count == 2
    policy.assert_awaited_once()

    with pytest.raises(ValueError, match='source differs'):
        asyncio.run(submission.initialize(**{**kwargs, 'source': tmp_path / 'changed'}))
    assert staged_policy.read_text() == 'original policy'
    importer.assert_awaited_once()


def test_submission_initializes_real_postgres_and_keeps_existing_turn(monkeypatch):
    from app.bootstrap import submission
    from app.configs import Settings
    from btc_data import btc_data_dir

    dsn = os.getenv('SUBMISSION_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('Set SUBMISSION_TEST_DATABASE_URL to a fresh dedicated test database')
    from sqlalchemy.engine import make_url

    database = make_url(dsn)
    backend_dsn = database.set(username='btc_test_backend', password='test-password').render_as_string(hide_password=False)
    reviewer_dsn = database.set(username='btc_test_reviewer', password='test-password').render_as_string(hide_password=False)
    worker_dsn = database.set(username='btc_test_worker', password='test-password').render_as_string(hide_password=False)
    monkeypatch.setenv('KNOWLEDGE_DATABASE_URL', reviewer_dsn)
    monkeypatch.setenv('KNOWLEDGE_WORKER_DATABASE_URL', worker_dsn)
    monkeypatch.setattr(submission, 'prepare_policy', AsyncMock())

    async def run():
        source = Path(btc_data_dir())
        settings = Settings(_env_file=None, app_env='test', llm_model='fake', llm_api_key='test',
                            knowledge_policy_source_dir=source / 'policy')
        args = dict(settings=settings, dsn=dsn, expected_database=database.database,
                    source=source, backend_dsn=backend_dsn,
                    mcp_passwords={name: 'abc123' for name in ('catalog', 'order', 'memory', 'knowledge')})
        assert await submission.initialize(**args, allow_policy_build=True) == 'initialized'
        conn = await submission.pg_connect(dsn)
        try:
            assert await conn.fetchval('SELECT count(*) FROM btc_source.products') > 0
            assert await conn.fetchval("SELECT to_regclass('runtime.store') IS NOT NULL")
            await conn.execute("""INSERT INTO runtime.turns (session_id,turn_no,channel,on_date,customer_text,agent_text)
                VALUES ('00000000-0000-0000-0000-000000000001',1,'hotline','2026-10-15','sample','sample')""")
        finally:
            await conn.close()
        assert await submission.initialize(**args) == 'already_initialized'
        await submission.verify_source(dsn, source)
        conn = await submission.pg_connect(backend_dsn)
        try:
            assert await conn.fetchval('SELECT count(*) FROM runtime.turns') == 1
        finally:
            await conn.close()

    asyncio.run(run())
