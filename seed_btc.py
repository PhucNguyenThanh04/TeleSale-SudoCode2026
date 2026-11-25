import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent


class SeedError(ValueError):
    pass


def configuration(root, source):
    from dotenv import dotenv_values

    path = root / '.env'
    if not path.is_file():
        raise SeedError('Place the completed .env in the repository root first.')
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None}
    values.update({key: os.environ[key] for key in values if key in os.environ})
    required = ['POSTGRES_PASSWORD', 'REVIEWER_PASSWORD', 'WORKER_PASSWORD', 'BACKEND_PASSWORD',
                'LLM_API_KEY', 'LLM_MODEL', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN',
                'DEMO_JWT_SECRET', 'DEMO_USER_1_PASSWORD', 'DEMO_USER_2_PASSWORD',
                *['MCP_' + name.upper() + '_PASSWORD' for name in ('catalog', 'order', 'memory', 'knowledge')]]
    missing = [key for key in required if not values.get(key, '').strip()]
    if missing:
        raise SeedError('Missing .env settings: ' + ', '.join(missing))
    defaults = {'SUBMISSION_POSTGRES_PORT': '15432', 'SUBMISSION_QDRANT_PORT': '16333',
                'SUBMISSION_AI_PORT': '18001', 'DEMO_PORT': '8000',
                **{'SUBMISSION_MCP_' + name.upper() + '_PORT': str(18011 + offset)
                   for offset, name in enumerate(('catalog', 'order', 'memory', 'knowledge'))}}
    for key, default in defaults.items():
        values[key] = values.get(key) or default
        if not values[key].isdigit() or not 1 <= int(values[key]) <= 65535:
            raise SeedError(key + ' must be a port between 1 and 65535')
    database = values.get('SUBMISSION_DATABASE') or 'telesale_eval_m1'
    if database != 'telesale_eval_m1':
        raise SeedError('Seed requires the dedicated telesale_eval_m1 database')
    port = int(values.get('SUBMISSION_POSTGRES_PORT', '15432'))
    def dsn(role, key):
        return f'postgresql+asyncpg://{role}:{quote(values[key], safe="")}@127.0.0.1:{port}/{database}'
    values.update(DATABASE_URL=dsn('btc_admin', 'POSTGRES_PASSWORD'),
        KNOWLEDGE_DATABASE_URL=dsn('btc_reviewer', 'REVIEWER_PASSWORD'),
        KNOWLEDGE_WORKER_DATABASE_URL=dsn('btc_worker', 'WORKER_PASSWORD'),
        BTC_BACKEND_DATABASE_URL=dsn('btc_backend', 'BACKEND_PASSWORD'),
        APP_ENV='development', SYSTEM_BOOT_ID='btc-submission-v1', MCP_DB_NAME=database,
        BTC_DATA_DIR=str(source), QDRANT_URL='http://127.0.0.1:' + values.get('SUBMISSION_QDRANT_PORT', '16333'),
        KNOWLEDGE_POLICY_SOURCE_DIR=str(root / 'runtime/policy'),
        KNOWLEDGE_POLICY_CONFIG_FILE=str(root / 'runtime/policy-runtime.host.json'))
    return values


async def initialize(root, source, values):
    from app.bootstrap.submission import initialize as initialize_database
    from app.bootstrap.mcp_roles import provision
    from app.configs import Settings, get_settings
    from scripts.prepare_knowledge_tokenizer import prepare

    Settings.model_config['env_file'] = None
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
    print('Importing BTC source, runtime schema and policy index...', flush=True)
    result = await initialize_database(settings=settings, dsn=values['DATABASE_URL'],
        expected_database=values['MCP_DB_NAME'], source=source,
        backend_dsn=values['BTC_BACKEND_DATABASE_URL'], allow_policy_build=True)
    print('Provisioning MCP database roles...', flush=True)
    await provision(values['DATABASE_URL'],
        {name: values['MCP_' + name.upper() + '_PASSWORD'] for name in ('catalog', 'order', 'memory', 'knowledge')})
    return result


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
        parser.exit(1, 'Install seed dependencies: python -m pip install -r config/submission/seed.txt\n')
    except SeedError as exc:
        parser.exit(1, 'Seed failed: ' + str(exc) + '\n')
    except Exception as exc:
        parser.exit(1, 'Seed failed (' + type(exc).__name__ + '). Check .env and the running services.\n')


if __name__ == '__main__':
    main()
