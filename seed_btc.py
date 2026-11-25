import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from scripts.btc_host import ConfigurationError as SeedError, configuration

ROOT = Path(__file__).resolve().parent


async def initialize(root, source, values):
    from app.bootstrap.submission import initialize as initialize_database
    from app.configs import Settings, get_settings
    from scripts.prepare_knowledge_tokenizer import prepare

    get_settings.cache_clear()
    config_path = root / 'config/policy-runtime.json'
    tokenizer = root / 'runtime/tokenizer/bge-m3-tokenizer.json'
    print('Preparing pinned tokenizer and policy configuration...', flush=True)
    prepare(config_path, tokenizer, download=True)
    tokenizer.chmod(0o644)
    config = json.loads(config_path.read_text())
    config['tokenizer_path'] = str(tokenizer)
    Path(values['KNOWLEDGE_POLICY_CONFIG_FILE']).write_text(json.dumps(config) + '\n')
    settings = Settings(_env_file=None)
    print('Importing BTC source, runtime schema, MCP roles and policy index...', flush=True)
    return await initialize_database(settings=settings, dsn=values['DATABASE_URL'],
        expected_database=values['MCP_DB_NAME'], source=source,
        backend_dsn=values['BTC_BACKEND_DATABASE_URL'],
        mcp_passwords={name: values['MCP_' + name.upper() + '_PASSWORD']
                       for name in ('catalog', 'order', 'memory', 'knowledge')},
        allow_policy_build=True)


def seed_accounts(root, values):
    environment = {**os.environ, **values, 'PYTHONPATH': str(root / 'backend') + os.pathsep + str(root)}
    for number in (1, 2):
        environment[f'DEMO_USER_{number}_USERNAME'] = f'demo{number}'
        environment[f'DEMO_USER_{number}_CUSTOMER_ID'] = values.get(f'DEMO_USER_{number}_CUSTOMER_ID', f'C00{number}')
    subprocess.run([sys.executable, '-m', 'app.seed_demo_users'], cwd=root, env=environment, check=True)


def wait_for_services(values):
    deadline = time.monotonic() + 180
    targets = {'backend': (values.get('DEMO_PORT', '8000'), '/chat'),
               'ai': (values.get('SUBMISSION_AI_PORT', '18001'), '/openapi.json')}
    for offset, name in enumerate(('catalog', 'order', 'memory', 'knowledge')):
        targets['mcp-' + name] = (values.get('SUBMISSION_MCP_' + name.upper() + '_PORT', str(18011 + offset)), None)
    pending = set(targets)
    while True:
        for name in list(pending):
            port, path = targets[name]
            try:
                if path:
                    with urlopen('http://127.0.0.1:' + port + path, timeout=3) as response:
                        if response.status != 200:
                            continue
                else:
                    with socket.create_connection(('127.0.0.1', int(port)), timeout=3):
                        pass
                pending.remove(name)
            except OSError:
                pass
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise SeedError('Data is initialized, but these services are not ready: ' + ', '.join(sorted(pending)))
        time.sleep(1)


def run(source, *, root=ROOT):
    source = source.resolve()
    if not source.is_dir():
        raise SeedError('--data-dir must point to the BTC data directory')
    values = configuration(root, source)
    os.environ.update(values)
    sys.path.insert(0, str(root / 'ai-services'))
    result = asyncio.run(initialize(root, source, values))
    print('Creating demo accounts...', flush=True)
    seed_accounts(root, values)
    from dotenv import set_key
    set_key(str(root / '.env'), 'BTC_ROOT', str(source), quote_mode='always')
    print('Waiting for AI, MCP servers and backend...', flush=True)
    wait_for_services(values)
    print('BTC data: ' + result + '; demo accounts, AI, MCP servers and backend are ready.')


def main():
    parser = argparse.ArgumentParser(description='Import BTC data from the host directly into the Docker databases')
    parser.add_argument('--data-dir', type=Path, required=True, help='Host path to BTC-Data-Vong1-TEAMS')
    args = parser.parse_args()
    try:
        run(args.data_dir)
    except ModuleNotFoundError:
        parser.exit(1, 'Install host dependencies: python -m pip install -r config/requirements/host.txt\n')
    except SeedError as exc:
        parser.exit(1, 'Seed failed: ' + str(exc) + '\n')
    except Exception as exc:
        parser.exit(1, 'Seed failed (' + type(exc).__name__ + '). Check .env and the running services.\n')


if __name__ == '__main__':
    main()
