import argparse
import os
from pathlib import Path
import subprocess
import sys

from scripts.btc_host import ConfigurationError, configuration, verify_seed


ROOT = Path(__file__).resolve().parent


def run(base_run, *, root=ROOT):
    values = configuration(root)
    verify_seed(root, values)
    return subprocess.run([sys.executable, '-u', '-m', 'eval_harness.knowledge_followup',
        '--base-run', str(base_run.resolve())], cwd=root, env={**os.environ, **values}).returncode


def main():
    parser = argparse.ArgumentParser(description='Evaluate published K1 on the host using the existing servers')
    parser.add_argument('--base-run', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.base_run)
    except ModuleNotFoundError:
        parser.exit(1, 'Install host dependencies: python -m pip install -r config/submission/host.txt\n')
    except ConfigurationError as exc:
        parser.exit(1, str(exc) + '\n')
    except OSError as exc:
        parser.exit(1, 'Knowledge evaluation failed (' + type(exc).__name__ + '). Check paths and file permissions.\n')
    raise SystemExit(result)

if __name__ == '__main__':
    main()
