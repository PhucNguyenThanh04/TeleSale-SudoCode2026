import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from eval_harness.benchmark_runner import preflight_runtime

IDENTITY = dict(database='telesale', host='db', port=5432, server_started_at='start')


@pytest.fixture(autouse=True)
def fake_runner_identity(monkeypatch):
    monkeypatch.setattr('eval_harness.benchmark_runner.database_url',lambda settings:'offline-dsn')
    monkeypatch.setattr('eval_harness.benchmark_runner.probe_runner_database',AsyncMock(return_value=IDENTITY))


def test_service_preflight_requires_explicit_target_and_all_four_services():
    tools = SimpleNamespace(database_identity=AsyncMock(return_value=IDENTITY),
                            knowledge_release=AsyncMock(return_value={'release_id':'r1','manifest_hash':'h'}))
    runtime = SimpleNamespace(tools=tools)
    settings = SimpleNamespace(app_env='test')
    with pytest.raises(ValueError):
        asyncio.run(preflight_runtime(runtime, settings, expected_database='', release={}))
    assert not tools.database_identity.called
    result = asyncio.run(preflight_runtime(runtime, settings, expected_database='telesale',
                release={'release_id':'r1','manifest_hash':'h'}))
    assert result == IDENTITY
    assert [c.args[0] for c in tools.database_identity.call_args_list] == ['catalog','order','memory','knowledge']
    tools.knowledge_release.side_effect = RuntimeError('not ready')
    with pytest.raises(RuntimeError):
        asyncio.run(preflight_runtime(runtime, settings, expected_database='telesale', release={'release_id':'r1','manifest_hash':'h'}))


def test_mismatched_identity_is_rejected():
    tools = SimpleNamespace(database_identity=AsyncMock(side_effect=[IDENTITY, {**IDENTITY, 'host':'other'}]))
    with pytest.raises(RuntimeError):
        asyncio.run(preflight_runtime(SimpleNamespace(tools=tools), SimpleNamespace(app_env='test'),
                                      expected_database='telesale', release={}))


def test_database_identity_reports_server_endpoint_not_client_dns():
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone
    from app.mcp_servers.mcp_shared.database import Database
    db=object.__new__(Database)
    row=SimpleNamespace(database='telesale',host='10.0.0.2',port=5432,
                        server_started_at=datetime(2026,1,1,tzinfo=timezone.utc))
    session=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(one=lambda:row)))
    @asynccontextmanager
    async def transaction():
        yield session
    class SessionContext:
        async def __aenter__(self): return session
        async def __aexit__(self,*args): pass
    db.sessions=SessionContext
    result=asyncio.run(db.database_identity())
    assert result['host']=='10.0.0.2' and result['port']==5432


def test_release_probe_requires_live_readiness_and_index_verification():
    from app.mcp_servers.mcp_knowledge.services.knowledge import PolicySearchService
    service=object.__new__(PolicySearchService)
    service.ready=False
    service.repo=SimpleNamespace(resolve_release=AsyncMock(return_value={'id':'r','manifest_hash':'h'}),
                                 snapshot=AsyncMock(return_value=[]))
    service.index=SimpleNamespace(verify=AsyncMock(side_effect=RuntimeError('index unavailable')))
    service.config=object()
    service._validate_release=lambda release: None
    with pytest.raises(RuntimeError):
        asyncio.run(service.release_ref('r'))
    service.ready=True
    with pytest.raises(RuntimeError):
        asyncio.run(service.release_ref('r'))
    assert service.index.verify.called


def test_runner_database_mismatch_is_rejected_before_any_model(offline_settings):
    from unittest.mock import patch
    tools=SimpleNamespace(database_identity=AsyncMock(return_value=IDENTITY),
        knowledge_release=AsyncMock(return_value={'release_id':'r1','manifest_hash':'h'}))
    with patch('eval_harness.benchmark_runner.probe_runner_database',new_callable=AsyncMock,
               return_value={**IDENTITY,'host':'wrong-server'},create=True):
        with pytest.raises(RuntimeError,match='runner'):
            asyncio.run(preflight_runtime(SimpleNamespace(tools=tools),offline_settings,
                expected_database='telesale',release={'release_id':'r1','manifest_hash':'h'}))


def test_knowledge_database_identity_bypasses_unit_of_work():
    from datetime import datetime, timezone
    from app.knowledge.repos.postgres import KnowledgeRepo
    row=SimpleNamespace(database='telesale',host='172.18.0.7/32',port=5432,
        server_started_at=datetime(2026,11,4,tzinfo=timezone.utc))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        def begin(self): return self
        execute=AsyncMock(return_value=SimpleNamespace(one=lambda:row))
    repo=object.__new__(KnowledgeRepo)
    repo.sessions=Session
    result=asyncio.run(repo.database_identity())
    assert result['database']=='telesale'
    assert result['host']=='172.18.0.7/32'
    assert Session.execute.await_count==1


def test_failed_preflight_report_identifies_service_without_raw_error(tmp_path,offline_settings):
    import json
    from eval_harness.benchmark_runner import execute_configuration
    tools=SimpleNamespace(database_identity=AsyncMock(side_effect=[IDENTITY,IDENTITY,IDENTITY,{'error':'mcp_unavailable'}]))
    runtime=SimpleNamespace(tools=tools,memory=SimpleNamespace(include_prior=True))
    with pytest.raises(RuntimeError):
        asyncio.run(execute_configuration(settings=offline_settings,scenarios={},config='full',
            run_id='r',out=tmp_path/'trace.jsonl',btc_root=tmp_path,expected_database='telesale',
            release={'release_id':'r1','manifest_hash':'h'},runtime=runtime))
    report=json.loads((tmp_path/'trace.report.json').read_text())
    assert report['error_code']=='mcp_database_identity_unavailable'
    assert report['phase']=='preflight' and report['service']=='knowledge'
