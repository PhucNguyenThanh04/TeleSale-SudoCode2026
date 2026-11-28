import argparse
import os
from pathlib import Path
import subprocess
import sys

from scripts.btc_host import ConfigurationError, configuration, verify_seed, ensure_utf8_mode


ROOT = Path(__file__).resolve().parent


def run(base_run=None, *, full_trace=None, root=ROOT):
    values = configuration(root)
    verify_seed(root, values)
    source = ['--full-trace', str(full_trace.resolve())] if full_trace is not None else ['--base-run', str(base_run.resolve())]
    return subprocess.run([sys.executable, '-u', '-m', 'eval_harness.knowledge_followup', *source],
                          cwd=root, env={**os.environ, **values}).returncode


def main():
    parser = argparse.ArgumentParser(description='Resume knowledge proposals or evaluate a published K1 release')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--base-run', type=Path, help='Evaluate a published K1 release from a prior pair')
    source.add_argument('--full-trace', type=Path, help='Resume proposals from a saved Full trace without model calls')
    args = parser.parse_args()
    try:
        result = run(args.base_run, full_trace=args.full_trace)
    except ModuleNotFoundError:
        parser.exit(1, 'Install host dependencies: python -m pip install -r config/requirements/host.txt\n')
    except ConfigurationError as exc:
        parser.exit(1, str(exc) + '\n')
    except OSError as exc:
        parser.exit(1, 'Knowledge evaluation failed (' + type(exc).__name__ + '). Check paths and file permissions.\n')
    raise SystemExit(result)

if __name__ == '__main__':
    ensure_utf8_mode()
    main()
