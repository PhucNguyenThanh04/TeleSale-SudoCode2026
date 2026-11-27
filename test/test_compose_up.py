import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(('gpu_exit', 'gpu_name', 'use_gpu'), [
    (0, 'NVIDIA GeForce RTX 3050 Laptop GPU', True),
    (1, '', False),
    (0, '', False),
])
def test_startup_selects_gpu_only_when_docker_can_access_it(tmp_path, gpu_exit, gpu_name, use_gpu):
    docker = tmp_path / 'docker'
    docker.write_text(f'#!{sys.executable}\n' + '''
import json
import os
from pathlib import Path
import sys

with Path(os.environ['DOCKER_CALLS']).open('a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'run':
    print(os.environ['GPU_NAME'])
    sys.exit(int(os.environ['GPU_EXIT']))
if sys.argv[1] == 'compose':
    sys.exit(int(os.environ['COMPOSE_EXIT']))
''')
    docker.chmod(0o755)
    calls_file = tmp_path / 'calls.jsonl'
    environment = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
                   'DOCKER_CALLS': str(calls_file), 'GPU_EXIT': str(gpu_exit),
                   'GPU_NAME': gpu_name, 'COMPOSE_EXIT': '0'}
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/compose_up.py')],
                            cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    probe = next(call for call in calls if call[0] == 'run')
    assert probe[probe.index('--gpus') + 1] == 'all'
    assert 'nvidia-smi' in probe
    compose = next(call for call in calls if call[0] == 'compose')
    assert compose[-3:] == ['up', '-d', '--build']
    assert str(ROOT / 'docker-compose.yml') in compose
    assert (str(ROOT / 'config/compose.gpu.yml') in compose) == use_gpu
    assert ('GPU' if use_gpu else 'CPU') in result.stdout
    environment['COMPOSE_EXIT'] = '7'
    failed = subprocess.run([sys.executable, str(ROOT / 'scripts/compose_up.py')],
                            cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert failed.returncode == 7
