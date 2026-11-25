import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock

from dotenv import dotenv_values, set_key
import pytest

import seed_btc


ROOT = Path(__file__).resolve().parents[1]


def environment(root, monkeypatch):
    text = (ROOT / '.env.example').read_text()
    text += '\nLLM_API_KEY=offline-key\nCLOUDFLARE_ACCOUNT_ID=' + 'a' * 32 + '\nCLOUDFLARE_API_TOKEN=offline-token\n'
    (root / '.env').write_text(text)
    for key in dotenv_values(root / '.env'):
        monkeypatch.delenv(key, raising=False)
    return root


def test_seed_uses_loopback_databases_and_encodes_passwords(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    set_key(str(tmp_path / '.env'), 'POSTGRES_PASSWORD', 'p@ss/word:1')
    values = seed_btc.configuration(tmp_path, tmp_path / 'official data')
    assert values['DATABASE_URL'] == 'postgresql+asyncpg://btc_admin:p%40ss%2Fword%3A1@127.0.0.1:15432/telesale_eval_m1'
    assert values['QDRANT_URL'] == 'http://127.0.0.1:16333'
    assert values['KNOWLEDGE_POLICY_SOURCE_DIR'] == str(tmp_path / 'runtime/policy')


def test_seed_initializes_accounts_and_saves_source_without_docker(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    source = tmp_path / 'official data'
    source.mkdir()
    initialize = AsyncMock(return_value='initialized')
    calls = []
    monkeypatch.setattr(seed_btc, 'initialize', initialize)
    monkeypatch.setattr(seed_btc, 'seed_accounts', lambda root, values: calls.append('accounts'))
    monkeypatch.setattr(seed_btc, 'wait_for_services', lambda values: calls.append('ready'))
    monkeypatch.setattr(seed_btc.os, 'environ', dict(os.environ))
    monkeypatch.setattr(seed_btc.sys, 'path', list(sys.path))
    seed_btc.run(source, root=tmp_path)
    assert initialize.call_args.args[:2] == (tmp_path, source)
    assert calls == ['accounts', 'ready']
    assert dotenv_values(tmp_path / '.env')['BTC_ROOT'] == str(source)


def test_failed_seed_preserves_previous_configuration(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    original = (tmp_path / '.env').read_bytes()
    source = tmp_path / 'changed source'
    source.mkdir()
    monkeypatch.setattr(seed_btc, 'initialize', AsyncMock(side_effect=ValueError('source mismatch')))
    monkeypatch.setattr(seed_btc.os, 'environ', dict(os.environ))
    monkeypatch.setattr(seed_btc.sys, 'path', list(sys.path))
    with pytest.raises(ValueError, match='source mismatch'):
        seed_btc.run(source, root=tmp_path)
    assert (tmp_path / '.env').read_bytes() == original


def test_account_seed_runs_python_directly(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    values = seed_btc.configuration(tmp_path, tmp_path)
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **options: calls.append((command, options)))
    seed_btc.seed_accounts(tmp_path, values)
    command, options = calls[0]
    assert command == [sys.executable, '-m', 'app.seed_demo_users']
    assert options['env']['DATABASE_URL'] == values['DATABASE_URL']
    assert options['env']['DEMO_USER_1_USERNAME'] == 'demo1'
    assert options['env']['DEMO_USER_2_CUSTOMER_ID'] == 'C002'
    assert options['env']['PYTHONPATH'].split(os.pathsep)[0] == str(tmp_path / 'backend')


def test_initializer_stages_tokenizer_and_provisions_roles(tmp_path, monkeypatch):
    from app.bootstrap import submission
    from scripts import prepare_knowledge_tokenizer

    environment(tmp_path, monkeypatch)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/policy-runtime.json').write_text('{}')
    values = seed_btc.configuration(tmp_path, tmp_path)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    initialize = AsyncMock(return_value='initialized')
    def prepare(config, target, **options):
        assert options == {'download': True}
        target.parent.mkdir(parents=True)
        target.write_text('verified-tokenizer')
    monkeypatch.setattr(prepare_knowledge_tokenizer, 'prepare', prepare)
    monkeypatch.setattr(submission, 'initialize', initialize)
    assert asyncio.run(seed_btc.initialize(tmp_path, tmp_path, values)) == 'initialized'
    config = json.loads(Path(values['KNOWLEDGE_POLICY_CONFIG_FILE']).read_text())
    assert config['tokenizer_path'] == str(tmp_path / 'runtime/tokenizer/bge-m3-tokenizer.json')
    assert initialize.call_args.kwargs['settings'].knowledge_policy_source_dir == tmp_path / 'runtime/policy'
    assert initialize.call_args.kwargs['allow_policy_build']
    assert set(initialize.call_args.kwargs['mcp_passwords']) == {'catalog', 'order', 'memory', 'knowledge'}


def test_seed_help_needs_no_docker_or_configuration():
    result = subprocess.run([sys.executable, str(ROOT / 'seed_btc.py'), '--help'],
                            capture_output=True, text=True, env={'PATH': '/unavailable'})
    assert result.returncode == 0
    assert '--data-dir' in result.stdout


def test_seed_rejects_missing_data_before_connecting():
    result = subprocess.run([sys.executable, '-S', str(ROOT / 'seed_btc.py'), '--data-dir', '/missing-btc-source'],
                            capture_output=True, text=True, env={'PATH': '/unavailable'})
    assert result.returncode == 1
    assert '--data-dir must point' in result.stderr


def test_seed_waits_for_ai_and_all_mcp_servers_without_docker(monkeypatch):
    from types import SimpleNamespace

    urls, ports, sleeps = [], [], []
    failed = False
    def connect(address, timeout):
        nonlocal failed
        ports.append(address[1])
        if address[1] == 18013 and not failed:
            failed = True
            raise OSError('starting')
        return nullcontext()
    monkeypatch.setattr(seed_btc, 'urlopen', lambda url, **kwargs:
        (urls.append(url) or nullcontext(SimpleNamespace(status=200))))
    monkeypatch.setattr(seed_btc.socket, 'create_connection', connect)
    monkeypatch.setattr(seed_btc.time, 'sleep', lambda seconds: sleeps.append(seconds))
    seed_btc.wait_for_services({})
    assert set(urls) == {'http://127.0.0.1:8000/chat', 'http://127.0.0.1:18001/openapi.json'}
    assert set(ports) == {18011, 18012, 18013, 18014}
    assert ports.count(18013) == 2
    assert sleeps == [1]
