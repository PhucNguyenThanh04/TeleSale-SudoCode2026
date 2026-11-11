from pathlib import Path
import importlib.util
from unittest.mock import patch

from app.configs import Settings


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


def test_worker_loads_local_profile_and_keeps_container_address(tmp_path):
    config = tmp_path / '.env'
    config.write_text('LLM_BACKEND=local\nLOCAL_LLM_MODEL=local-qwen\n'
                      'LOCAL_LLM_BASE_URL=http://localhost:8081/v1\n'
                      'LOCAL_LLM_API_KEY=local-secret\nLANGMEM_MODEL=cloud-memory\n')
    result = startup().service_environment('app.mcp_servers.mcp_memory.distiller_worker', config,
        {'LOCAL_LLM_BASE_URL': 'http://host.docker.internal:8081/v1'})
    with patch.dict('os.environ', result, clear=True):
        settings = Settings(_env_file=None)
    assert settings.llm_model == 'local-qwen'
    assert settings.langmem_model == 'local-qwen'
    assert str(settings.llm_base_url) == 'http://host.docker.internal:8081/v1'
    assert settings.llm_api_key.get_secret_value() == 'local-secret'


def test_local_worker_entrypoint_does_not_require_a_cloud_key(monkeypatch):
    module = startup()
    command = ['python', '-m', 'app.mcp_servers.mcp_memory.distiller_worker']
    captured = []
    monkeypatch.setattr(module.sys, 'argv', ['container_start.py', *command])
    monkeypatch.setattr(module.os, 'execvpe', lambda binary, args, env: captured.append(args))
    with patch.dict(module.os.environ, {'LLM_BACKEND': 'local', 'LLM_API_KEY': ''}, clear=True):
        module.main()
    assert captured == [command]
