import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock

from dotenv import dotenv_values, set_key
import pytest

import run_eval
import run_knowledge_eval
from scripts import btc_host


ROOT = Path(__file__).resolve().parents[1]


def environment(root, monkeypatch):
    text = (ROOT / '.env.example').read_text()
    text += '\nLLM_API_KEY=offline-key\nCLOUDFLARE_ACCOUNT_ID=offline-account\nCLOUDFLARE_API_TOKEN=offline-token\n'
    (root / '.env').write_text(text)
    for key in dotenv_values(root / '.env'):
        monkeypatch.delenv(key, raising=False)
    return root


@pytest.mark.parametrize('selected', [None, 'full', 'baseline_no_memory'])
def test_eval_runs_host_python_with_btc_paths_and_existing_servers(tmp_path, monkeypatch, selected):
    environment(tmp_path, monkeypatch)
    scenarios = tmp_path / 'hidden scenarios'
    scenarios.mkdir()
    output = tmp_path / 'output with spaces'
    if selected:
        output /= selected + '.jsonl'
    args = argparse.Namespace(scenarios=scenarios, config=selected, out=output,
                              seed=7, limit_scenarios=None)
    verify = []
    calls = []
    monkeypatch.setattr(run_eval, 'verify_seed', lambda root, values: verify.append(values))
    monkeypatch.setattr(run_eval.subprocess, 'run',
        lambda command, **options: calls.append((command, options)) or subprocess.CompletedProcess(command, 0))
    monkeypatch.setenv('PATH', '/no-docker-or-sudo')
    assert run_eval.run(args, root=tmp_path) == 0
    command, options = calls[0]
    assert command[:3] == [sys.executable, '-u', '-m']
    assert command[3] == ('eval.run_eval' if selected else 'eval_harness.run_official')
    assert all(word not in command for word in ('docker', 'sudo', 'compose', 'up', '--build'))
    assert command[command.index('--scenarios') + 1] == str(scenarios)
    assert command[command.index('--btc-root') + 1] == str((tmp_path / '../BTC-Data-Vong1-TEAMS').resolve())
    assert command[command.index('--expected-database') + 1] == 'telesale_eval_m1'
    assert command[-2:] == ['--seed', '7']
    assert options['cwd'] == tmp_path
    assert options['env']['MCP_CATALOG_URL'] == 'http://127.0.0.1:18011/mcp'
    assert options['env']['AI_ENV_FILE'] == str(tmp_path / '.env')
    assert verify[0]['DATABASE_URL'] == options['env']['DATABASE_URL']
    if selected:
        assert command[command.index('--config') + 1] == selected
        assert command[command.index('--out') + 1] == str(output)
        assert '--isolated-db' in command
    else:
        assert command[command.index('--out-root') + 1] == str(output)


@pytest.mark.parametrize('sidecar', ['', '.report.json', '.btc-release'])
def test_existing_trace_or_failed_attempt_is_preserved(tmp_path, sidecar):
    output = tmp_path / 'trace.jsonl'
    saved = output.with_suffix(sidecar) if sidecar else output
    saved.write_text('saved')
    args = argparse.Namespace(scenarios=None, config='full', out=output, seed=7, limit_scenarios=None)
    with pytest.raises(FileExistsError):
        run_eval.run(args, root=tmp_path)
    assert saved.read_text() == 'saved'


def test_default_pair_resolves_env_paths_and_smoke_option(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    (tmp_path / 'custom-scenarios').mkdir()
    set_key(str(tmp_path / '.env'), 'SCENARIOS_DIR', './custom-scenarios')
    set_key(str(tmp_path / '.env'), 'RESULTS_DIR', './custom-results')
    args = argparse.Namespace(scenarios=None, config=None, out=None, seed=13, limit_scenarios=1)
    calls = []
    monkeypatch.setattr(run_eval, 'verify_seed', lambda *args: None)
    monkeypatch.setattr(run_eval.subprocess, 'run',
        lambda command, **options: calls.append(command) or subprocess.CompletedProcess(command, 0))
    assert run_eval.run(args, root=tmp_path) == 0
    command = calls[0]
    assert command[command.index('--scenarios') + 1] == str(tmp_path / 'custom-scenarios')
    assert command[command.index('--out-root') + 1] == str(tmp_path / 'custom-results')
    assert command[command.index('--limit-scenarios') + 1] == '1'
    assert command[-1] == '13'


def test_seed_verification_failure_prevents_evaluation(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    source = tmp_path / 'btc'
    source.mkdir()
    (tmp_path / 'runtime').mkdir()
    (tmp_path / 'runtime/policy-runtime.host.json').write_text('{}')
    values = btc_host.configuration(tmp_path, source)
    from app.bootstrap import submission
    monkeypatch.setattr(submission, 'verify_source', AsyncMock(side_effect=ValueError('private-password')))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    with pytest.raises(btc_host.ConfigurationError, match='Seed verification failed') as error:
        btc_host.verify_seed(tmp_path, values)
    assert 'private-password' not in str(error.value)


def test_custom_ports_and_root_env_are_used_in_python_child(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    for key, value in {'SUBMISSION_POSTGRES_PORT': '25432', 'SUBMISSION_QDRANT_PORT': '26333',
                       'SUBMISSION_MCP_KNOWLEDGE_PORT': '28014', 'LLM_TEMPERATURE': '0.7'}.items():
        set_key(str(tmp_path / '.env'), key, value)
    values = btc_host.configuration(tmp_path)
    assert ':25432/' in values['DATABASE_URL']
    assert values['QDRANT_URL'] == 'http://127.0.0.1:26333'
    assert values['MCP_KNOWLEDGE_URL'] == 'http://127.0.0.1:28014/mcp'
    script = ('import sys,json;sys.path.insert(0,sys.argv[1]);from app.configs import Settings;'
              's=Settings();print(json.dumps([s.llm_temperature,s.knowledge_enabled,s.mcp_knowledge_url]))')
    result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'ai-services')],
        cwd=tmp_path, env={**os.environ, **values}, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [0.7, True, 'http://127.0.0.1:28014/mcp']


def test_failed_preflight_prints_report_location_and_service(tmp_path, monkeypatch, capsys):
    environment(tmp_path, monkeypatch)
    scenarios = tmp_path / 'scenarios'
    scenarios.mkdir()
    output = tmp_path / 'full.jsonl'
    args = argparse.Namespace(scenarios=scenarios, config='full', out=output, seed=7, limit_scenarios=None)
    monkeypatch.setattr(run_eval, 'verify_seed', lambda *args: None)
    def execute(command, **options):
        output.with_suffix('.report.json').write_text(json.dumps({'phase': 'preflight',
            'error_code': 'mcp_database_identity_unavailable', 'service': 'knowledge'}))
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(run_eval.subprocess, 'run', execute)
    assert run_eval.run(args, root=tmp_path) == 1
    error = capsys.readouterr().err
    assert 'preflight' in error and 'service=knowledge' in error
    assert str(output.with_suffix('.report.json')) in error


def test_knowledge_followup_runs_on_host_with_same_configuration(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(run_knowledge_eval, 'verify_seed', lambda *args: None)
    monkeypatch.setattr(run_knowledge_eval.subprocess, 'run',
        lambda command, **options: calls.append((command, options)) or subprocess.CompletedProcess(command, 0))
    base = tmp_path / 'pair with spaces'
    assert run_knowledge_eval.run(base, root=tmp_path) == 0
    command, options = calls[0]
    assert command == [sys.executable, '-u', '-m', 'eval_harness.knowledge_followup', '--base-run', str(base)]
    assert options['env'] == {**os.environ, **btc_host.configuration(tmp_path)}


@pytest.mark.parametrize('script', ['seed_btc.py', 'run_eval.py', 'run_knowledge_eval.py'])
def test_help_runs_without_docker_configuration_or_dependencies(script):
    result = subprocess.run([sys.executable, '-S', str(ROOT / script), '--help'],
                            capture_output=True, text=True, env={'PATH': '/unavailable'})
    assert result.returncode == 0


@pytest.mark.parametrize('selected', ['full', 'baseline_no_memory'])
def test_main_accepts_the_btc_command_line(monkeypatch, selected):
    captured = []
    monkeypatch.setattr(run_eval, 'run', lambda args: captured.append(args) or 0)
    monkeypatch.setattr(sys, 'argv', ['run_eval.py', '--scenarios', 'hidden cases',
        '--config', selected, '--out', 'results/trace.jsonl'])
    with pytest.raises(SystemExit) as result:
        run_eval.main()
    assert result.value.code == 0
    args = captured[0]
    assert (args.scenarios, args.config, args.out) == (Path('hidden cases'), selected, Path('results/trace.jsonl'))


def test_optional_blank_settings_match_compose_defaults(tmp_path, monkeypatch):
    environment(tmp_path, monkeypatch)
    for key in ('SUBMISSION_POSTGRES_PORT', 'LLM_BASE_URL', 'LLM_TIMEOUT_SECONDS', 'CLOUDFLARE_API_BASE_URL'):
        set_key(str(tmp_path / '.env'), key, '')
    values = btc_host.configuration(tmp_path)
    assert ':15432/' in values['DATABASE_URL']
    assert values['LLM_BASE_URL'] == 'https://api.openai.com/v1'
    assert values['LLM_TIMEOUT_SECONDS'] == '30'
    assert values['CLOUDFLARE_API_BASE_URL'] == 'https://api.cloudflare.com/client/v4'
