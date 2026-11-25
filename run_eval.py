import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.btc_host import configuration, verify_seed


ROOT = Path(__file__).resolve().parent


def run(args, *, root=ROOT):
    root = Path(root).resolve()
    if args.config and args.out is None:
        raise ValueError('--out is required with --config')
    if args.config and args.limit_scenarios is not None:
        raise ValueError('--limit-scenarios is available only for paired evaluation')
    output = args.out.resolve() if args.out is not None else None
    if args.config and any(path.exists() for path in (output, output.with_suffix('.report.json'),
                                                      output.with_suffix('.btc-release'))):
        raise FileExistsError('Trace already exists; choose a new --out path.')
    values = configuration(root)
    scenarios = (args.scenarios.resolve() if args.scenarios is not None else
                 (root / (values.get('SCENARIOS_DIR') or './eval/scenario_final')).resolve())
    if not scenarios.is_dir():
        raise ValueError('--scenarios must be an existing directory')
    output = output or (root / (values.get('RESULTS_DIR') or './results-submission')).resolve()
    verify_seed(root, values)
    environment = {**os.environ, **values}
    command = [sys.executable, '-u', '-m']
    if args.config:
        command += ['eval.run_eval', '--config', args.config, '--out', str(output), '--isolated-db']
    else:
        command += ['eval_harness.run_official', '--out-root', str(output)]
        if args.limit_scenarios is not None:
            command += ['--limit-scenarios', str(args.limit_scenarios)]
    command += ['--scenarios', str(scenarios), '--btc-root', values['BTC_DATA_DIR'],
                '--expected-database', values['EVAL_EXPECTED_DATABASE'], '--seed', str(args.seed)]
    result = subprocess.run(command, cwd=root, env=environment).returncode
    if result and args.config:
        report = output.with_suffix('.report.json')
        if report.is_file():
            details = json.loads(report.read_text())
            print(f"Eval failed: phase={details.get('phase')} code={details.get('error_code')} "
                  f"service={details.get('service')}. Report: {report}", file=sys.stderr)
            if details.get('verification_rejections'):
                print('Verification rejected: ' + ', '.join(details['verification_rejections']), file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(description='Run BTC evaluation on the host against the running, seeded servers')
    parser.add_argument('--scenarios', type=Path, help='Host directory; defaults to SCENARIOS_DIR in .env')
    parser.add_argument('--config', choices=('full', 'baseline_no_memory'),
        help='Export one trace; omit to compare Full and baseline and print metrics')
    parser.add_argument('--out', type=Path, help='Trace JSONL with --config; output directory otherwise')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--limit-scenarios', type=int, help='Run a paired smoke test on a subset')
    args = parser.parse_args()
    try:
        result = run(args)
    except ModuleNotFoundError:
        parser.exit(1, 'Install host dependencies: python -m pip install -r config/requirements/host.txt\n')
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, str(exc) + '\n')
    except OSError as exc:
        parser.exit(1, 'Host evaluation failed (' + type(exc).__name__ + '). Check paths and file permissions.\n')
    raise SystemExit(result)


if __name__ == '__main__':
    main()
