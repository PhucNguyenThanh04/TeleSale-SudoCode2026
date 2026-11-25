import argparse
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
