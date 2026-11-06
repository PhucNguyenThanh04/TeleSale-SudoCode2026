from pathlib import Path
import importlib.util


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
