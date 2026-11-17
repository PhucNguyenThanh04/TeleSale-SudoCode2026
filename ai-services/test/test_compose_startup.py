from pathlib import Path
import importlib.util
from unittest.mock import patch



def startup():
    path = Path(__file__).resolve().parents[1] / 'scripts/container_start.py'
    spec = importlib.util.spec_from_file_location('container_start', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_reads_saved_settings_without_host_db_or_unrelated_secrets(tmp_path):
    config = tmp_path / '.env'
    config.write_text('LLM_API_KEY=offline-key\nLLM_MODEL=offline-model\nDATABASE_URL=host-admin\nMCP_INTERNAL_TOKEN=host-token\nCLOUDFLARE_API_TOKEN=other-secret\nEVAL_DECISION_DIAGNOSTICS=1\n')
    env = {'MCP_DB_HOST': 'postgres', 'PATH': '/bin'}
    result = startup().service_environment('app.mcp_servers.mcp_memory.distiller_worker', config, env)
    assert result['LLM_API_KEY'] == 'offline-key'
    assert result['EVAL_DECISION_DIAGNOSTICS'] == '1'
    assert result['MCP_DB_HOST'] == 'postgres'
    assert not {'DATABASE_URL','MCP_INTERNAL_TOKEN','CLOUDFLARE_API_TOKEN'} & result.keys()


def test_knowledge_receives_only_its_provider_settings_and_keeps_compose_overrides(tmp_path):
    config = tmp_path / '.env'
    config.write_text('CLOUDFLARE_ACCOUNT_ID=offline-account\nCLOUDFLARE_API_TOKEN=offline-token\nLLM_API_KEY=other-secret\nQDRANT_URL=http://localhost:6333\n')
    result = startup().service_environment('app.mcp_servers.mcp_knowledge.server', config,
        {'QDRANT_URL': 'http://qdrant:6333', 'LLM_API_KEY': 'unused-for-mcp'})
    assert result['CLOUDFLARE_API_TOKEN'] == 'offline-token'
    assert result['LLM_API_KEY'] == 'unused-for-mcp'
    assert result['QDRANT_URL'] == 'http://qdrant:6333'






def test_managed_container_checks_boot_with_its_own_database_role(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from sqlalchemy.engine import make_url
    module = startup(); captured = []
    password = tmp_path/'password'; password.write_text('abc123')
    check = AsyncMock()
    monkeypatch.setattr('app.bootstrap.database.require_ready', check)
    monkeypatch.setattr(module.sys, 'argv', ['container_start.py', 'python', '-m', 'app.mcp_servers.mcp_memory.server'])
    monkeypatch.setattr(module.os, 'execvpe', lambda binary, args, env: captured.append(env))
    with patch.dict(module.os.environ, {'LLM_API_KEY': 'unused', 'LLM_MODEL': 'unused',
            'MCP_DB_HOST': 'postgres', 'MCP_DB_NAME': 'fixture', 'MCP_DB_USER': 'mcp_memory',
            'MCP_DB_PASSWORD_FILE': str(password), 'SYSTEM_BOOT_ID': 'boot-1'}, clear=True):
        module.main()
    check.assert_awaited_once()
    assert make_url(check.call_args.args[0]).username == 'mcp_memory'
    assert check.call_args.args[1] == 'boot-1'
    assert captured[0]['SYSTEM_BOOT_ID'] == 'boot-1'
