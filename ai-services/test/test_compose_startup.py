import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.engine import make_url


def test_mcp_starts_with_its_own_database_role_after_seed(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / 'scripts/container_start.py'
    spec = importlib.util.spec_from_file_location('container_start', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    password = tmp_path / 'password'
    password.write_text('abc123')
    wait = AsyncMock()
    commands = []
    command = ['python', '-m', 'app.mcp_servers.mcp_memory.server']
    monkeypatch.setattr(module, 'wait_for_seed', wait)
    monkeypatch.setattr(module.sys, 'argv', ['container_start.py', *command])
    monkeypatch.setattr(module.os, 'execvp', lambda binary, args: commands.append((binary, args)))
    with patch.dict(module.os.environ, {'LLM_API_KEY': 'unused', 'LLM_MODEL': 'unused',
            'MCP_DB_HOST': 'postgres', 'MCP_DB_NAME': 'fixture', 'MCP_DB_USER': 'mcp_memory',
            'MCP_DB_PASSWORD_FILE': str(password), 'SYSTEM_BOOT_ID': 'boot-1'}, clear=True):
        module.main()
    wait.assert_awaited_once()
    assert make_url(wait.call_args.args[0]).username == 'mcp_memory'
    assert wait.call_args.args[1] == 'boot-1'
    assert commands == [('python', command)]
