import argparse
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


def run(args, *, root=ROOT):
    root = Path(root).resolve()
    if not (root / '.env').is_file():
        raise ValueError('Place the completed .env in the repository root first.')
    if args.config and args.out is None:
        raise ValueError('--out is required with --config')
    if args.config and args.limit_scenarios is not None:
        raise ValueError('--limit-scenarios is available only for paired evaluation')
    environment = dict(os.environ)
    environment['SUBMISSION_RUN_AS'] = f'{os.getuid()}:{os.getgid()}'
    if args.scenarios is not None:
        scenarios = args.scenarios.resolve()
        if not scenarios.is_dir():
            raise ValueError('--scenarios must be an existing directory')
        environment['SCENARIOS_DIR'] = str(scenarios)
    output = args.out.resolve() if args.out is not None else None
    if args.config and output.exists():
        raise FileExistsError('Trace already exists; choose a new --out path.')
    if output is not None:
        environment['RESULTS_DIR'] = str(output.parent if args.config else output)
    compose = ['docker', 'compose', '--env-file', str(root / '.env'),
               '-f', str(root / 'compose.submission.yml')]
    resolved = subprocess.run([*compose, '--profile', 'eval', 'config', '--format', 'json'],
        cwd=root, env=environment, check=True, capture_output=True, text=True)
    config = json.loads(resolved.stdout)
    results = next(mount['source'] for mount in config['services']['eval']['volumes']
                   if mount['target'] == '/results')
    (Path(results) / 'models').mkdir(parents=True, exist_ok=True)
    command = [*compose, 'run', '--rm', '--no-deps']
    if args.config:
        command += ['eval-trace', '--scenarios', '/scenarios', '--config', args.config,
                    '--out', '/results/' + output.name, '--seed', str(args.seed)]
    else:
        command += ['eval', '--seed', str(args.seed)]
        if args.limit_scenarios is not None:
            command += ['--limit-scenarios', str(args.limit_scenarios)]
    return subprocess.run(command, cwd=root, env=environment).returncode


def main():
    parser = argparse.ArgumentParser(description='Evaluate the running, seeded Docker stack using the BTC interface')
    parser.add_argument('--scenarios', type=Path, help='Host directory; defaults to SCENARIOS_DIR in .env')
    parser.add_argument('--config', choices=('full', 'baseline_no_memory'),
        help='Export one trace; omit to compare Full and baseline and print metrics')
    parser.add_argument('--out', type=Path, help='Trace JSONL with --config; output directory otherwise')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--limit-scenarios', type=int, help='Run a paired smoke test on a subset')
    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, str(exc) + '\n')
    except (OSError, subprocess.CalledProcessError):
        parser.exit(1, 'Docker evaluation failed. Check .env, start Docker Compose and run ./seed_btc.sh first.\n')
    raise SystemExit(result)


if __name__ == '__main__':
    main()
