from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL)
    if result.returncode:
        return result.returncode
    print('Checking NVIDIA GPU access through Docker...', flush=True)
    probe = subprocess.run([
        'docker', 'run', '--rm', '--gpus', 'all',
        'nvidia/cuda:13.0.2-base-ubuntu24.04',
        'nvidia-smi', '--query-gpu=name', '--format=csv,noheader',
    ], capture_output=True, text=True)
    command = ['docker', 'compose', '-f', str(ROOT / 'docker-compose.yml')]
    if probe.returncode == 0 and probe.stdout.strip():
        print('Speech: GPU (' + probe.stdout.strip() + ')', flush=True)
        command += ['-f', str(ROOT / 'config/compose.gpu.yml')]
    else:
        print('Speech: CPU (NVIDIA CUDA unavailable in Docker)', flush=True)
        if probe.stderr.strip():
            print(probe.stderr.strip(), file=sys.stderr)
    return subprocess.run([*command, 'up', '-d', '--build'], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
