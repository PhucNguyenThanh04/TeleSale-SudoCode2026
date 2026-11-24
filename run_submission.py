import argparse
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


def launch(service, arguments, *, root=ROOT):
    root = Path(root).resolve()
    if not (root / '.env').is_file():
        raise ValueError('Copy .env.example to .env and fill in the BTC API credentials first.')
    environment = dict(os.environ)
    demo = service == 'demo'
    environment['SUBMISSION_DATABASE'] = 'telesale_demo' if demo else 'telesale_eval_m1'
    environment['BTC_CALLBACK_MOCK'] = '0' if service in {'demo', 'asr'} else '1'
    project = 'telesale-btc-demo' if demo else 'telesale-btc-eval'
    compose = ['docker', 'compose', '--env-file', str(root / '.env'),
               '-f', str(root / 'compose.submission.yml'), '-p', project]
    result = subprocess.run([*compose, 'config', '--environment'], cwd=root,
        env=environment, check=True, capture_output=True, text=True)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if service != 'asr':
        missing = [name for name in ('LLM_API_KEY', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN')
                   if not values.get(name, '').strip()]
        if missing:
            raise ValueError('Missing values in .env: ' + ', '.join(missing))
    environment['SUBMISSION_RUN_AS'] = values.get('SUBMISSION_RUN_AS') or f'{os.getuid()}:{os.getgid()}'
    result = subprocess.run([*compose, '--profile', '*', 'config', '--format', 'json'],
        cwd=root, env=environment, check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    results = next(mount['source'] for mount in config['services']['eval']['volumes']
                   if mount['target'] == '/results')
    (Path(results) / 'models').mkdir(parents=True, exist_ok=True)
    command = (['up', '-d', '--build', '--wait', 'backend'] if demo
               else ['run', '--rm', '--build', service])
    return subprocess.run([*compose, *command, *arguments], cwd=root, env=environment).returncode


def main():
    parser = argparse.ArgumentParser(description='Run the Docker submission stack using .env')
    parser.add_argument('service', nargs='?', default='eval',
        choices=('eval', 'demo', 'eval-trace', 'knowledge-eval', 'asr'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        code = launch(args.service, args.arguments)
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')
    except (OSError, subprocess.CalledProcessError):
        parser.exit(1, 'Cannot prepare the submission. Check Docker Compose, .env and directory permissions.\n')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
