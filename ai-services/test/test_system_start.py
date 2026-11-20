import asyncio
from argparse import Namespace
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize('mode', ['demo', 'knowledge-eval'])
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
    args = Namespace(mode=mode,
        expected_database='telesale', command=[], resume=None)
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
    args = Namespace(mode='knowledge-eval', expected_database='telesale', command=[],
        resume=Path('existing'))
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


def test_missing_review_plan_fails_before_settings_or_service_start(monkeypatch, tmp_path, capsys):
    from app import system_start as mod
    monkeypatch.setattr('sys.argv', ['system_start', 'knowledge-eval', '--expected-database',
        'telesale', '--', '--approval-plan', str(tmp_path/'missing.json')])
    monkeypatch.setattr(mod, 'get_settings', lambda: pytest.fail('must validate plan before startup'))
    with pytest.raises(SystemExit):
        mod.main()
    assert '--approval-plan must point to an existing valid' in capsys.readouterr().err


def test_lock_does_not_use_container_owned_storage(monkeypatch, tmp_path):
    from app import system_start as mod
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    assert mod.startup_lock_path() == tmp_path/'.system-start.lock'


@pytest.mark.parametrize('options', [[], ['--auto-review']])
def test_automatic_knowledge_start_does_not_require_review_plan(monkeypatch, options):
    from app import system_start as mod
    monkeypatch.setattr('sys.argv', ['system_start', 'knowledge-eval', '--expected-database',
        'telesale', '--', *options])
    def stop_before_startup(): raise RuntimeError('configuration reached without plan')
    monkeypatch.setattr(mod, 'get_settings', stop_before_startup)
    with pytest.raises(RuntimeError, match='configuration reached without plan'):
        mod.main()


@pytest.mark.parametrize('options', [['--auto-review', '--approval-plan', 'plan.json']])
def test_conflicting_review_modes_fail_before_startup(monkeypatch, capsys, options):
    from app import system_start as mod
    monkeypatch.setattr('sys.argv', ['system_start', 'knowledge-eval', '--expected-database',
        'telesale', '--', *options])
    monkeypatch.setattr(mod, 'get_settings', lambda: pytest.fail('must not start with conflicting modes'))
    with pytest.raises(SystemExit): mod.main()
    assert 'not allowed with argument' in capsys.readouterr().err


@pytest.mark.parametrize('failure', [False, True])
def test_public_eval_uses_running_stack_without_docker_bootstrap_or_demo_lock(monkeypatch, tmp_path, failure):
    from app import system_start as mod
    import fcntl
    import subprocess
    commands = []
    monkeypatch.setattr('sys.argv', ['system_start', 'eval', '--expected-database', 'telesale',
        '--', '--btc-root', '/btc', '--scenarios', '/scenarios'])
    monkeypatch.setenv('SYSTEM_BOOT_ID', 'running-demo-boot')
    monkeypatch.setenv('KNOWLEDGE_RELEASE_ID', 'chosen-k0')
    monkeypatch.setattr(mod, 'get_settings', lambda: pytest.fail('eval uses runner configuration'))
    monkeypatch.setattr(mod, 'compose', lambda *a: pytest.fail('eval must not control Docker'))
    monkeypatch.setattr(mod, 'BootDatabase', lambda *a, **kw: pytest.fail('no schema bootstrap'))
    monkeypatch.setattr(mod, 'check_host_ports', lambda *a: pytest.fail('ports belong to running services'))
    monkeypatch.setattr(mod.subprocess, 'Popen', lambda *a, **kw: pytest.fail('do not start servers'))
    monkeypatch.setattr(mod, 'startup_lock_path', lambda: tmp_path/'demo.lock')
    def run(command, **kwargs):
        commands.append((command, kwargs['env']))
        if failure: raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(mod, 'run', run)
    with (tmp_path/'demo.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if failure:
            with pytest.raises(SystemExit) as exc: mod.main()
            assert exc.value.code == 1
        else:
            mod.main()
    assert len(commands) == 1
    command, env = commands[0]
    assert command[2] == 'eval_harness.run_official'
    assert command[-2:] == ['--expected-database', 'telesale']
    assert not {'--delivery-mode', '--streaming', '--agent'} & set(command)
    assert env['SYSTEM_BOOT_ID'] == 'running-demo-boot'
    assert env['KNOWLEDGE_RELEASE_ID'] == 'chosen-k0'


def test_removed_manual_flag_fails_before_startup(monkeypatch, tmp_path, capsys):
    from app import system_start as mod
    monkeypatch.setattr('sys.argv', ['system_start', 'knowledge-eval', '--expected-database',
        'telesale', '--', '--manual-review'])
    monkeypatch.setattr(mod, 'get_settings', lambda: pytest.fail('no startup/reset'))
    with pytest.raises(SystemExit): mod.main()
    assert 'run_knowledge_eval.py' in capsys.readouterr().err
