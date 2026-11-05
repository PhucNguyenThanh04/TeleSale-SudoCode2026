"""Functional loader checks; no live DB, model, or BTC evaluations."""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from btc_data import btc_data_dir

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataloader_offline.source import read_release


def test_policy_import_uses_the_same_safe_content_and_hashes_as_publisher():
    from app.knowledge.policy.source import default_metadata, parse_policy_sources
    release = read_release(btc_data_dir())
    rows = {row.chunk_id: row for row in release['chunks']}
    serving = parse_policy_sources(btc_data_dir() / 'policy', default_metadata())
    assert len(rows) == 99
    assert len({row.document_id for row in rows.values()}) == 14
    assert sum(row.access_level == 'public' for row in rows.values()) == 93
    for chunk in serving:
        row = rows[chunk.chunk_id]
        assert row.body == chunk.content
        assert row.content_hash == chunk.source_hash
        assert row.date_basis == ('call_date' if chunk.date_basis == 'on' else 'order_date')
        assert row.effective_from == (chunk.effective_from.isoformat() if chunk.effective_from else None)
    assert 'dược sĩ' in rows['PB-06'].body
    assert '19/10/2026' in rows['NB-02'].body
    assert rows['NQ-01'].access_level == 'restricted'
    assert '90%' not in rows['KM-06'].body


def test_policy_metadata_override_is_shared_with_source_validation(tmp_path):
    from app.knowledge.policy.source import default_metadata
    metadata = default_metadata()
    metadata['sections']['PB-06']['effective_from'] = '2026-11-01'
    path = tmp_path / 'metadata.json'
    path.write_text(json.dumps(metadata))
    release = read_release(btc_data_dir(), metadata_path=path)
    row = next(row for row in release['chunks'] if row.chunk_id == 'PB-06')
    assert row.effective_from == '2026-11-01'


def test_dry_run_with_policy_prepare_never_connects_or_encodes(monkeypatch, capsys):
    from dataloader_offline import __main__ as cli
    from dataloader_offline import knowledge, postgres
    prepare = AsyncMock(side_effect=AssertionError('must not build'))
    monkeypatch.setattr(knowledge, 'prepare_policy', prepare)
    monkeypatch.setattr(postgres, 'import_release', AsyncMock(side_effect=AssertionError('must not write')))
    monkeypatch.setattr(cli, 'database_url', lambda: pytest.fail('must not resolve DB'))
    monkeypatch.setattr(sys, 'argv', ['loader', '--dry-run', '--prepare-policy', '--actor', 'reviewer',
                                    '--runtime-config', '/not-read-on-dry-run.json',
                                    '--data-dir', str(btc_data_dir())])
    cli.main()
    prepare.assert_not_awaited()
    output = capsys.readouterr().out
    assert "'public_chunks': 93" in output
    assert "'crm_orders': 2" in output


def test_policy_prepare_needs_explicit_actor_and_config_before_any_write(monkeypatch):
    from dataloader_offline import __main__ as cli
    monkeypatch.setattr(sys, 'argv', ['loader', '--prepare-policy'])
    monkeypatch.setattr(cli, 'database_url', lambda: pytest.fail('must validate arguments first'))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_missing_runtime_config_explains_setup_before_reading_source_or_db(monkeypatch, tmp_path, capsys):
    from dataloader_offline import __main__ as cli
    missing = tmp_path / 'policy-runtime.json'
    monkeypatch.setattr(sys, 'argv', ['loader', '--prepare-policy', '--actor', 'REVIEWER',
                                    '--runtime-config', str(missing)])
    monkeypatch.setattr(cli, 'read_release', lambda *a, **kw: pytest.fail('must validate config first'))
    monkeypatch.setattr(cli, 'database_url', lambda: pytest.fail('must not connect'))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert '--runtime-config file does not exist' in captured.err
    assert 'dataloader_offline/README.md' in captured.err
    assert not captured.out


def test_verify_cannot_override_dry_run_no_connection_guarantee(monkeypatch):
    from dataloader_offline import __main__ as cli
    monkeypatch.setattr(sys, 'argv', ['loader', '--dry-run', '--verify-postgres'])
    monkeypatch.setattr(cli, 'database_url', lambda: pytest.fail('must not connect'))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_default_import_never_starts_policy_encoding(monkeypatch, capsys):
    from argparse import Namespace
    from dataloader_offline import __main__ as loader, knowledge, postgres
    writer = AsyncMock(return_value={'policy_chunks': 99})
    prepare = AsyncMock(side_effect=AssertionError('must not encode'))
    monkeypatch.setattr(postgres, 'import_release', writer)
    monkeypatch.setattr(knowledge, 'prepare_policy', prepare)
    monkeypatch.setattr(knowledge, 'validate_policy_prepare', AsyncMock(side_effect=AssertionError('must not connect')))
    monkeypatch.setattr(loader, 'database_url', lambda: 'postgresql://offline-replay')
    asyncio.run(loader.import_data(Namespace(prepare_policy=False), {}))
    writer.assert_awaited_once()
    prepare.assert_not_awaited()
    assert 'index not built' in capsys.readouterr().out


def test_explicit_prepare_uses_existing_release_workflow_without_activation(monkeypatch, tmp_path):
    from dataloader_offline import knowledge
    from app.knowledge import cli
    execute = AsyncMock(return_value={'id': 'policy-test', 'status': 'prepared'})
    monkeypatch.setattr(cli, 'execute', execute)
    source = tmp_path / 'btc'
    config = tmp_path / 'runtime.json'
    result = asyncio.run(knowledge.prepare_policy(source, actor='reviewer', runtime_config=config,
        metadata_path=None, expected_active='old-release', revision_ids=['approved-revision']))
    assert result['status'] == 'prepared'
    execute.assert_awaited_once()
    args = execute.await_args.args[0]
    assert args.action == 'policy-prepare'
    assert args.source_dir == source / 'policy'
    assert args.runtime_config == config
    assert args.expected_active == 'old-release'
    assert args.revision_id == ['approved-revision']


@pytest.mark.parametrize('reason', ['permission', 'active', 'config'])
def test_prepare_preflight_failure_prevents_source_writes(monkeypatch, tmp_path, reason):
    from argparse import Namespace
    from dataloader_offline import __main__ as loader, postgres
    from app.knowledge import config
    from app.knowledge.repos import postgres as knowledge_postgres
    from test_knowledge_repo import MemoryRepo
    from test_policy_embedding import runtime_config

    repo = MemoryRepo()
    repo.close = AsyncMock()
    if reason != 'permission':
        repo.tables['permissions'] = {'reviewer': {'permissions': ['knowledge_review']}}
    if reason == 'active':
        repo.tables['active'] = {'current': {'release_id': 'newer'}}
    path = tmp_path / 'runtime.json'
    path.write_text('{}' if reason == 'config' else runtime_config().model_dump_json())
    monkeypatch.setattr(config, 'configured_url', lambda key: 'unused-dsn')
    monkeypatch.setattr(knowledge_postgres, 'KnowledgeRepo', lambda dsn: repo)
    writer = AsyncMock(side_effect=AssertionError('must not write'))
    monkeypatch.setattr(postgres, 'import_release', writer)
    args = Namespace(prepare_policy=True, actor='reviewer', runtime_config=path, expected_active=None)
    with pytest.raises(ValueError):
        asyncio.run(loader.import_data(args, {}))
    writer.assert_not_awaited()


def test_import_and_prepare_builds_complete_snapshot_without_activation(monkeypatch, tmp_path):
    from argparse import Namespace
    import re
    from qdrant_client import AsyncQdrantClient
    from dataloader_offline import __main__ as loader
    from app.knowledge import cli, config
    from app.knowledge.repos import postgres as knowledge_postgres
    from app.knowledge.services import publish
    from app.knowledge.policy.source import default_metadata
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from test_knowledge_repo import MemoryRepo
    from test_policy_embedding import Backend, runtime_config

    class Writer:
        def __init__(self):
            self.rows = {}

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def execute(self, sql, *args):
            match = re.search(r'INSERT INTO btc_source\.(\w+)', sql)
            if match:
                table = match[1]
                key = args[:2] if table == 'inventory_events' else args[0]
                self.rows.setdefault(table, {})[key] = args

        async def close(self):
            pass

    async def run():
        repo = MemoryRepo()
        repo.close = AsyncMock()
        await repo.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
        writer = Writer()
        from dataloader_offline import knowledge as loader_knowledge
        monkeypatch.setattr(loader_knowledge, '_check_prepare_dependencies', AsyncMock())
        monkeypatch.setattr('asyncpg.connect', AsyncMock(return_value=writer))
        monkeypatch.setattr(loader, 'database_url', lambda: 'postgresql://offline-replay')
        monkeypatch.setattr(config, 'configured_url', lambda key: 'unused-dsn')
        monkeypatch.setattr(cli, 'configured_url', lambda key: 'unused-dsn')
        monkeypatch.setattr(knowledge_postgres, 'KnowledgeRepo', lambda dsn: repo)
        monkeypatch.setattr(cli, 'KnowledgeRepo', lambda dsn: repo)
        runtime = runtime_config(max_tokens=8000, relevance_verified=False)
        path = tmp_path / 'runtime.json'
        path.write_text(runtime.model_dump_json())
        encoder = PolicyEncoder(runtime, Backend())
        client = AsyncQdrantClient(':memory:')

        async def configured_build(repo, revision_ids, expected_active_id, actor_id, **kwargs):
            assert kwargs['source_dir'] == btc_data_dir() / 'policy'
            return await publish.build_policy_release(repo, encoder, HybridPolicyIndex(client),
                source_dir=kwargs['source_dir'], metadata=default_metadata(), revision_ids=revision_ids,
                expected_active_id=expected_active_id, actor_id=actor_id)

        monkeypatch.setattr(publish, 'build_configured_policy_release', configured_build)
        args = Namespace(prepare_policy=True, actor='reviewer', runtime_config=path,
            expected_active=None, data_dir=btc_data_dir(), metadata=None, revision_id=[])
        try:
            await loader.import_data(args, read_release(btc_data_dir()))
            assert {t: len(rows) for t, rows in writer.rows.items()} == {
                'products': 40, 'variants': 96, 'promotions': 13, 'inventory_events': 12,
                'customers': 50, 'crm_orders': 2, 'crm_sessions': 3,
                'policy_documents': 14, 'policy_chunks': 99}
            releases = await repo.rows('releases')
            assert len(releases) == 1
            release = releases[0]
            assert release['status'] == 'ready'
            assert release['manifest']['checks']['relevance_verified'] is False
            assert release['manifest']['checks']['index_complete']
            assert len(await repo.rows('policy_sources')) == 93
            assert await repo.get('active', 'current') is None
            assert (await client.get_collection(release['manifest']['collection'])).points_count == 93
        finally:
            await encoder.close()
            await client.close()

    asyncio.run(run())


def test_qdrant_url_uses_shared_settings_and_environment_precedence(monkeypatch):
    from app.knowledge import config
    from types import SimpleNamespace
    monkeypatch.delenv('QDRANT_URL', raising=False)
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(qdrant_url='http://from-env-file:6333'))
    assert config.qdrant_url() == 'http://from-env-file:6333'
    monkeypatch.setenv('QDRANT_URL', 'http://from-process:6333')
    assert config.qdrant_url() == 'http://from-process:6333'


@pytest.mark.parametrize('failure', ['account','token','asset'])
def test_runtime_preflight_rejects_missing_requirements_without_model_load(monkeypatch, failure):
    from dataloader_offline.knowledge import _validate_provider_runtime
    from test_policy_embedding import runtime_config
    from types import SimpleNamespace
    from pydantic import SecretStr
    monkeypatch.setattr('app.configs.get_settings', lambda:SimpleNamespace(
        cloudflare_account_id=None if failure=='account' else 'a'*32,
        cloudflare_api_token=None if failure=='token' else SecretStr('fake')))
    if failure=='asset':
        monkeypatch.setattr('app.mcp_servers.mcp_knowledge.services.embedding.load_tokenizer',
            lambda c:(_ for _ in ()).throw(ValueError('Tokenizer asset hash mismatch')))
    with pytest.raises(ValueError):
        _validate_provider_runtime(runtime_config())


@pytest.mark.parametrize('reason', ['table','privilege','database','qdrant'])
def test_dependency_preflight_reads_only_and_rejects_wrong_targets(monkeypatch, reason):
    from dataloader_offline import knowledge
    from app.knowledge import config
    from test_policy_embedding import runtime_config
    monkeypatch.setattr(knowledge, '_validate_provider_runtime', lambda config:None)
    monkeypatch.setattr(config, 'qdrant_url', lambda:'http://synthetic:6333')
    class Conn:
        def __init__(self,dsn):self.dsn=dsn
        @asynccontextmanager
        async def transaction(self,**kwargs):
            assert kwargs == {'readonly':True}
            yield
        async def fetchrow(self,sql):
            return {'database':'other' if reason=='database' and self.dsn.endswith('source') else 'test', 'server_epoch':'1'}
        async def fetchval(self,sql,*args):
            return not (reason=='table' and 'to_regclass' in sql or reason=='privilege' and 'has_table_privilege' in sql)
        async def close(self):pass
    async def connect(dsn,**kwargs):return Conn(dsn)
    class Qdrant:
        def __init__(self,**kwargs):assert kwargs['url']=='http://synthetic:6333'
        async def get_collections(self):
            if reason=='qdrant':raise ConnectionError('synthetic')
        async def close(self):pass
    monkeypatch.setattr('asyncpg.connect',connect)
    monkeypatch.setattr('qdrant_client.AsyncQdrantClient',Qdrant)
    with pytest.raises((ValueError,ConnectionError)):
        asyncio.run(knowledge._check_prepare_dependencies(runtime_config(),'postgresql://reviewer','postgresql://source'))


@pytest.mark.parametrize('status,exit_code',[('passed',0),('failed',1)])
def test_verify_ingestion_cli_never_imports_and_returns_correct_exit(monkeypatch,tmp_path,capsys,status,exit_code):
    from dataloader_offline import __main__ as cli,verification,postgres
    from app.knowledge import config
    cfg=tmp_path/'runtime.json';cfg.write_text('{}')
    monkeypatch.setattr(sys,'argv',['loader','--verify-ingestion','--release-id','release',
        '--runtime-config',str(cfg)])
    monkeypatch.setattr(cli,'database_url',lambda:'postgresql://synthetic')
    monkeypatch.setattr(config,'configured_url',lambda key:'postgresql://reviewer')
    monkeypatch.setattr(config,'qdrant_url',lambda:'http://correct-instance:6333')
    verify=AsyncMock(return_value={'ingestion_status':status})
    monkeypatch.setattr(verification,'verify_ingestion',verify)
    monkeypatch.setattr(postgres,'import_release',AsyncMock(side_effect=AssertionError('must not write')))
    with pytest.raises(SystemExit) as exc:cli.main()
    assert exc.value.code==exit_code
    assert json.loads(capsys.readouterr().out)['ingestion_status']==status
    assert verify.await_args.kwargs['qdrant_url']=='http://correct-instance:6333'


@pytest.mark.parametrize('extra', ['--prepare-policy','--verify-postgres','--only-postgres','--dry-run'])
def test_verify_ingestion_rejects_write_or_other_modes(monkeypatch,extra):
    from dataloader_offline import __main__ as cli
    monkeypatch.setattr(sys,'argv',['loader','--verify-ingestion',extra])
    with pytest.raises(SystemExit) as exc:cli.main()
    assert exc.value.code==2


def test_source_change_after_postgres_is_reported_as_partial_failure(monkeypatch):
    from argparse import Namespace
    from dataloader_offline import __main__ as cli,knowledge,postgres
    monkeypatch.setattr(cli,'database_url',lambda:'postgresql://synthetic')
    monkeypatch.setattr(knowledge,'validate_policy_prepare',AsyncMock())
    fingerprint=['original']
    monkeypatch.setattr(cli,'source_fingerprint',lambda *a:fingerprint[0])
    async def writer(*args):
        fingerprint[0]='changed'
        return {}
    monkeypatch.setattr(postgres,'import_release',writer)
    prepare=AsyncMock(side_effect=AssertionError('must not build mixed source'))
    monkeypatch.setattr(knowledge,'prepare_policy',prepare)
    args=Namespace(prepare_policy=True,actor='test',runtime_config='test',expected_active=None,
        data_dir=Path('.'),metadata=None,revision_id=[])
    with pytest.raises(cli.ImportStageError,match='stage=policy_prepare; source_commit_confirmed=True'):
        asyncio.run(cli.import_data(args,{'source_fingerprint':'original'}))
    prepare.assert_not_awaited()


@pytest.mark.parametrize('reason,status,code',[
    ('quota_exhausted',429,'3036'),('auth',401,'10000'),('invalid_response',200,None),
])
def test_cloudflare_failure_reports_safe_provider_details(monkeypatch,reason,status,code):
    from argparse import Namespace
    from dataloader_offline import __main__ as cli,knowledge,postgres
    from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
    monkeypatch.setattr(cli,'database_url',lambda:'postgresql://synthetic')
    monkeypatch.setattr(knowledge,'validate_policy_prepare',AsyncMock())
    monkeypatch.setattr(postgres,'import_release',AsyncMock(return_value={}))
    monkeypatch.setattr(knowledge,'prepare_policy',AsyncMock(side_effect=PolicyProviderError(
        reason,status=status,provider_code=code)))
    args=Namespace(prepare_policy=True,actor='test',runtime_config='test',expected_active=None,
        data_dir=Path('.'),metadata=None,revision_id=[])
    with pytest.raises(cli.ImportStageError) as caught:
        asyncio.run(cli.import_data(args,{}))
    message=str(caught.value)
    assert 'stage=policy_prepare; source_commit_confirmed=True' in message
    assert 'reason='+reason in message
    assert 'http_status='+str(status) in message
    if code:assert 'provider_code='+code in message


def test_generic_import_failure_never_prints_exception_secrets(monkeypatch):
    from argparse import Namespace
    from dataloader_offline import __main__ as cli,knowledge,postgres
    monkeypatch.setattr(cli,'database_url',lambda:'postgresql://synthetic')
    monkeypatch.setattr(knowledge,'validate_policy_prepare',AsyncMock())
    monkeypatch.setattr(postgres,'import_release',AsyncMock(side_effect=ValueError('secret-do-not-print')))
    args=Namespace(prepare_policy=True,actor='test',runtime_config='test',expected_active=None,
        data_dir=Path('.'),metadata=None,revision_id=[])
    with pytest.raises(cli.ImportStageError) as caught:asyncio.run(cli.import_data(args,{}))
    assert 'secret-do-not-print' not in str(caught.value)
