"""Managed startup owns one boot, ahead of every server and eval arm."""
import asyncio
from argparse import Namespace
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize('mode', ['demo', 'eval', 'knowledge-eval'])
def test_startup_creates_resets_and_seeds_before_starting_servers(monkeypatch, tmp_path, mode):
    from app import system_start as mod
    events = []
    class Boot:
        def __init__(self, *args, **kwargs):
            self.ready = False; self.connection = SimpleNamespace(fetchval=AsyncMock(return_value=None))
        async def __aenter__(self): events.append('lock'); return self
        async def __aexit__(self, *args): events.append('unlock')
        async def create_fresh_schema(self): events.append('schema')
        async def mark_ready(self): events.append('ready')
    monkeypatch.setattr(mod, 'BootDatabase', Boot)
    async def store(*args): events.append('store')
    async def roles(*args): events.append('roles')
    async def policy(*args): events.append('base-policy')
    async def fingerprint(*args): return 'source'
    monkeypatch.setattr(mod, 'setup_store', store)
    monkeypatch.setattr(mod, 'setup_logins', roles)
    monkeypatch.setattr(mod, 'setup_policy', policy)
    monkeypatch.setattr(mod, 'fingerprint_btc_source', fingerprint)
    monkeypatch.setattr(mod, 'compose', lambda *args: events.append(('compose', args)))
    monkeypatch.setattr(mod, 'seed_accounts', lambda *args: events.append('accounts'))
    monkeypatch.setattr(mod, 'check_configuration', lambda *args: None)
    monkeypatch.setattr(mod, 'check_host_ports', lambda *args: None)
    monkeypatch.setattr(mod, 'verify_backend_database', AsyncMock())
    monkeypatch.setattr(mod, 'serve', lambda *args: events.append('serve'))
    monkeypatch.setattr(mod, 'wait_services', lambda *args: events.append('ports-ready'))
    monkeypatch.setattr(mod, 'database_url', lambda _: 'postgresql://offline')
    monkeypatch.setattr(mod, 'capture_base', AsyncMock(return_value=None))
    settings = SimpleNamespace(app_env='test')
    args = Namespace(mode=mode, expected_database='telesale', command=[], resume=None)
    env = {'SYSTEM_BOOT_ID': 'boot-1'}
    asyncio.run(mod.start(args, settings, env))
    assert events.index('schema') < events.index('store') < events.index('roles')
    assert events.index('base-policy') < events.index('ready') < events.index('serve')
    assert events.count('schema') == 1
    assert ('accounts' in events) is (mode == 'demo')


def test_resume_does_not_create_new_boot_or_reset_any_schema(monkeypatch):
    from app import system_start as mod
    resets = []
    monkeypatch.setattr(mod, 'require_ready', AsyncMock())
    monkeypatch.setattr(mod, 'check_configuration', lambda *args: None)
    monkeypatch.setattr(mod, 'verify_backend_database', AsyncMock())
    monkeypatch.setattr(mod, 'serve', lambda *args: resets.append('resume'))
    monkeypatch.setattr(mod, 'wait_services', lambda *args: None)
    monkeypatch.setattr(mod, 'compose', lambda *args: resets.append(args))
    monkeypatch.setattr(mod, 'database_url', lambda _: 'postgresql://offline')
    args = Namespace(mode='knowledge-eval', expected_database='telesale', command=[], resume=Path('existing'))
    asyncio.run(mod.start(args, SimpleNamespace(app_env='test'), {'SYSTEM_BOOT_ID': 'boot-1'}))
    assert resets == [('up', '-d', *mod.MCP), 'resume']


def test_optional_sudo_is_limited_to_docker_and_preserves_boot_id(monkeypatch):
    from app import system_start as mod
    calls = []
    monkeypatch.setenv('SYSTEM_SUDO_DOCKER', '1')
    monkeypatch.setattr(mod, 'run', lambda command: calls.append(command))
    mod.compose('up', '-d', 'postgres')
    assert calls[0][:3] == ['sudo', '--preserve-env=SYSTEM_BOOT_ID', 'docker']
    assert calls[0][-3:] == ['up', '-d', 'postgres']


def test_stale_resume_does_not_take_ownership_or_stop_current_services(monkeypatch):
    from app import system_start as mod
    monkeypatch.setattr(mod, 'check_configuration', lambda *args: None)
    monkeypatch.setattr(mod, 'require_ready', AsyncMock(side_effect=ValueError('old boot')))
    monkeypatch.setattr(mod, 'compose', lambda *args: pytest.fail('must leave current stack untouched'))
    monkeypatch.setattr(mod, 'database_url', lambda _: 'postgresql://offline')
    env = {'SYSTEM_BOOT_ID': 'old'}
    args = Namespace(mode='knowledge-eval', resume=Path('existing'))
    with pytest.raises(ValueError): asyncio.run(mod.start(args, None, env))
    assert 'SYSTEM_STACK_OWNER' not in env


def test_empty_release_override_uses_active_release_instead_of_old_env_file_pin(monkeypatch):
    from app.knowledge import config
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(knowledge_release_id='old-deleted-release'))
    monkeypatch.delenv('KNOWLEDGE_RELEASE_ID', raising=False)
    assert config.pinned_release() == 'old-deleted-release'
    monkeypatch.setenv('KNOWLEDGE_RELEASE_ID', '')
    assert config.pinned_release() is None
    monkeypatch.setenv('KNOWLEDGE_RELEASE_ID', 'explicit-eval-release')
    assert config.pinned_release() == 'explicit-eval-release'


def test_invalid_startup_configuration_leaves_existing_services_untouched(monkeypatch):
    from app import system_start as mod
    def invalid(*args): raise mod.StartupError('invalid configuration')
    monkeypatch.setattr(mod, 'check_configuration', invalid)
    monkeypatch.setattr(mod, 'compose', lambda *args: pytest.fail('must not stop current services'))
    env = {'SYSTEM_BOOT_ID': 'new'}
    with pytest.raises(ValueError): asyncio.run(mod.start(Namespace(mode='demo'), None, env))
    assert 'SYSTEM_STACK_OWNER' not in env
