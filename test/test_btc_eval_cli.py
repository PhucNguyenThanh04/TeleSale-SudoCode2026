import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import run_eval


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('configuration', [None, 'full', 'baseline_no_memory'])
def test_eval_script_uses_existing_stack_and_host_paths(tmp_path, monkeypatch, configuration):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose CLI is required')
    shutil.copyfile(ROOT / 'compose.submission.yml', tmp_path / 'compose.submission.yml')
    (tmp_path / '.env').write_text((ROOT / '.env.example').read_text())
    scenarios = tmp_path / 'hidden scenarios'
    scenarios.mkdir()
    output = tmp_path / 'output with spaces'
    if configuration:
        output /= configuration + '.jsonl'
    args = argparse.Namespace(scenarios=scenarios, config=configuration, out=output,
                              seed=7, limit_scenarios=None)
    original = subprocess.run
    executions = []

    def execute(command, **kwargs):
        if 'config' in command:
            return original(command, **kwargs)
        executions.append((command, kwargs))
        return subprocess.CompletedProcess(command, 19)

    monkeypatch.setattr(run_eval.subprocess, 'run', execute)
    assert run_eval.run(args, root=tmp_path) == 19
    command, options = executions[0]
    assert '--no-deps' in command
    assert '--build' not in command and 'up' not in command and 'seed' not in command
    assert options['env']['SCENARIOS_DIR'] == str(scenarios)
    assert options['env']['SUBMISSION_RUN_AS'] == f'{os.getuid()}:{os.getgid()}'
    results = output.parent if configuration else output
    assert options['env']['RESULTS_DIR'] == str(results)
    assert (results / 'models').is_dir()
    if configuration:
        assert command[-9:] == ['eval-trace', '--scenarios', '/scenarios', '--config', configuration,
                                '--out', '/results/' + output.name, '--seed', '7']
    else:
        assert command[-3:] == ['eval', '--seed', '7']


def test_existing_trace_is_preserved(tmp_path):
    (tmp_path / '.env').write_text('')
    output = tmp_path / 'trace.jsonl'
    output.write_text('saved')
    args = argparse.Namespace(scenarios=None, config='full', out=output,
                              seed=7, limit_scenarios=None)
    with pytest.raises(FileExistsError):
        run_eval.run(args, root=tmp_path)
    assert output.read_text() == 'saved'


def test_default_pair_uses_env_output_directory_and_smoke_option(tmp_path, monkeypatch):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose CLI is required')
    shutil.copyfile(ROOT / 'compose.submission.yml', tmp_path / 'compose.submission.yml')
    (tmp_path / '.env').write_text((ROOT / '.env.example').read_text() + '\nRESULTS_DIR=./custom-results\n')
    args = argparse.Namespace(scenarios=None, config=None, out=None, seed=7, limit_scenarios=1)
    original = subprocess.run
    executions = []

    def execute(command, **kwargs):
        if 'config' in command:
            return original(command, **kwargs)
        executions.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_eval.subprocess, 'run', execute)
    assert run_eval.run(args, root=tmp_path) == 0
    assert (tmp_path / 'custom-results/models').is_dir()
    assert executions[0][-5:] == ['eval', '--seed', '7', '--limit-scenarios', '1']


@pytest.mark.parametrize('failure', [False, True])
def test_seed_script_seeds_then_checks_service_readiness(tmp_path, failure):
    shutil.copyfile(ROOT / 'seed_btc.sh', tmp_path / 'seed_btc.sh')
    (tmp_path / '.env').write_text('UNUSED=$(touch must-not-exist)\n')
    tools = tmp_path / 'bin'
    tools.mkdir()
    docker = tools / 'docker'
    docker.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ['FAIL_SEED'] == '1' and 'seed' in sys.argv:
    raise SystemExit(19)
''')
    docker.chmod(0o755)
    log = tmp_path / 'calls.jsonl'
    environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       CALL_LOG=str(log), FAIL_SEED='1' if failure else '0')
    result = subprocess.run(['bash', str(tmp_path / 'seed_btc.sh')], cwd=tmp_path,
                            env=environment, capture_output=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0][-3:] == ['run', '--rm', 'seed']
    assert len(calls) == (1 if failure else 2)
    if not failure:
        assert calls[1][-5:] == ['up', '-d', '--wait', '--wait-timeout', '180']
    assert result.returncode == (19 if failure else 0)
    assert not (tmp_path / 'must-not-exist').exists()
