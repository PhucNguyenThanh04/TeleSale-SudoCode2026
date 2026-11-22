import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_demo_and_eval_compose_projects_have_separate_storage_and_entrypoints(tmp_path):
    if not shutil.which('docker'):
        pytest.skip('Docker CLI is needed to resolve Compose')
    env_file = tmp_path / 'env'

    def config(project, database):
        env_file.write_text(f'SUBMISSION_DATABASE={database}\nSUBMISSION_RUN_AS=1123:1345\n')
        completed = subprocess.run(
            ['docker', 'compose', '--env-file', str(env_file), '-f', 'compose.submission.yml',
             '-p', project, '--profile', '*', 'config', '--format', 'json'],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        return json.loads(completed.stdout)

    demo = config('btc-demo-check', 'telesale_demo')
    evaluation = config('btc-eval-check', 'telesale_eval_m1')
    for config_data in (demo, evaluation):
        services = config_data['services']
        assert set(services) >= {'setup', 'ai', 'backend', 'eval', 'eval-trace', 'knowledge-eval', 'asr',
                                 'mcp-memory', 'mcp-knowledge', 'knowledge-worker', 'langmem-worker'}
        assert all('container_name' not in service for service in services.values())
        assert [name for name, service in services.items() if service.get('ports')] == ['backend']
        assert services['postgres']['volumes'][0]['type'] == 'volume'
        assert services['setup']['volumes'][0]['read_only']
        assert 'eval_harness.run_official' in services['eval']['entrypoint']
        assert '/workspace/run_eval.py' in services['eval-trace']['entrypoint']
        mounts = {m['target']: m for m in services['eval']['volumes']}
        assert mounts['/btc']['read_only'] and mounts['/scenarios']['read_only']
        assert mounts['/asr-btc-input']['read_only'] and mounts['/asr-team-input']['read_only']
        assert not mounts['/results'].get('read_only')
        assert 'backend' not in services['eval']['depends_on']
        assert 'setup' not in services['backend']['depends_on']
        assert all(services[name]['user'] == '1123:1345'
                   for name in ('eval', 'eval-trace', 'knowledge-eval', 'asr'))
        model_mount, = [mount for mount in services['asr']['volumes'] if mount['target'] == '/models']
        assert model_mount['type'] == 'bind'
        assert model_mount['source'].endswith('/results-submission/models')
    assert {v['name'] for v in demo['volumes'].values()}.isdisjoint(
        v['name'] for v in evaluation['volumes'].values()
    )
    assert demo['services']['postgres']['environment']['POSTGRES_DB'] == 'telesale_demo'
    assert evaluation['services']['postgres']['environment']['POSTGRES_DB'] == 'telesale_eval_m1'
    assert evaluation['services']['eval']['environment']['BTC_SUBMISSION_PROJECT'] == 'btc-eval-check'
    assert evaluation['services']['eval']['environment']['BTC_SUBMISSION_DEMO_PORT'] == '8000'
