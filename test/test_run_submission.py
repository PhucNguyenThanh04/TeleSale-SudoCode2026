import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import run_submission


ROOT = Path(__file__).resolve().parents[1]


def test_missing_supplied_env_reports_the_handoff_step(tmp_path):
    with pytest.raises(ValueError, match='Place the .env supplied by the team'):
        run_submission.launch('eval', [], root=tmp_path)


@pytest.mark.parametrize('service,arguments', [('eval', []), ('demo', []),
    ('eval-trace', ['--config', 'full', '--out', '/results/full.jsonl']),
    ('asr', ['transcribe', '--audio', '/audio-dataset/audio', '--out', '/results/asr-team'])])
def test_supplied_env_prepares_directories_and_runs_compose(tmp_path, monkeypatch, service, arguments):
    if not shutil.which('docker'):
        pytest.skip('Docker CLI is needed to resolve Compose')
    for name in ('LLM_API_KEY', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN', 'SUBMISSION_RUN_AS'):
        monkeypatch.delenv(name, raising=False)
    text = (ROOT / '.env.example').read_text()
    if service != 'asr':
        text += '\nLLM_API_KEY=offline-key\nCLOUDFLARE_ACCOUNT_ID=offline-account\nCLOUDFLARE_API_TOKEN=offline-token\n'
    results = 'custom-results' if service == 'eval-trace' else 'results-submission'
    run_as = '1123:1345' if service == 'eval-trace' else f'{os.getuid()}:{os.getgid()}'
    if service == 'eval-trace':
        text += f'RESULTS_DIR=./{results}\nSUBMISSION_RUN_AS={run_as}\n'
    (tmp_path / '.env').write_text(text)
    shutil.copyfile(ROOT / 'compose.submission.yml', tmp_path / 'compose.submission.yml')
    original = subprocess.run
    launches = []
    values = {}

    def execute(command, **kwargs):
        if 'config' in command:
            result = original(command, **kwargs)
            if '--environment' in command:
                values.update(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            if '--format' in command:
                config = json.loads(result.stdout)
                assert all('file' not in value and value.get('environment')
                           for value in config['secrets'].values())
                assert all(values.get(value['environment']) for value in config['secrets'].values())
                for name in ('eval', 'eval-trace', 'mcp-order'):
                    assert config['services'][name]['environment']['BTC_CALLBACK_MOCK'] == (
                        '0' if service in {'demo', 'asr'} else '1')
            return result
        launches.append((command, kwargs))
        return subprocess.CompletedProcess(command, 19)

    monkeypatch.setattr(run_submission.subprocess, 'run', execute)
    assert run_submission.launch(service, arguments, root=tmp_path) == 19
    assert (tmp_path / results / 'models').is_dir()
    assert not (tmp_path / 'secrets-submission').exists()
    assert not (tmp_path / 'backend/.env').exists()
    assert not (tmp_path / 'ai-services/.env').exists()
    command, options = launches[0]
    assert options['env']['SUBMISSION_RUN_AS'] == run_as
    assert options['env']['SUBMISSION_DATABASE'] == ('telesale_demo' if service == 'demo' else 'telesale_eval_m1')
    if service == 'demo':
        assert command[-5:] == ['up', '-d', '--build', '--wait', 'backend']
    else:
        tail = ['run', '--rm', '--build', service, *arguments]
        assert command[-len(tail):] == tail


def test_missing_api_credentials_stop_before_launch(tmp_path, monkeypatch):
    if not shutil.which('docker'):
        pytest.skip('Docker CLI is needed to resolve Compose')
    for name in ('LLM_API_KEY', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / '.env').write_text((ROOT / '.env.example').read_text())
    shutil.copyfile(ROOT / 'compose.submission.yml', tmp_path / 'compose.submission.yml')
    with pytest.raises(ValueError, match='LLM_API_KEY'):
        run_submission.launch('eval', [], root=tmp_path)
    assert not (tmp_path / 'results-submission').exists()
