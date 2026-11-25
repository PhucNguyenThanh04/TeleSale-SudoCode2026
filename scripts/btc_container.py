import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote


SECRETS = Path('/run/secrets')


def secret(name):
    value = (SECRETS / name).read_text().strip()
    if not value:
        raise ValueError(f'Empty file for {name}')
    return value


def database(user, password_file):
    login = quote(user, safe='')
    password = quote(secret(password_file), safe='')
    name = quote(os.environ['MCP_DB_NAME'], safe='')
    return f'postgresql+asyncpg://{login}:{password}@postgres:5432/{name}'


async def wait_for_seed(dsn, boot_id):
    import asyncpg

    announced = False
    while True:
        connection = None
        try:
            connection = await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1), timeout=3)
            if await connection.fetchval("SELECT to_regclass('system_boot.current')"):
                state = await connection.fetchrow('SELECT boot_id,status FROM system_boot.current WHERE singleton')
                if state and state['status'] == 'ready':
                    if state['boot_id'] != boot_id:
                        raise ValueError('Database belongs to a different managed startup')
                    return
        except (asyncpg.PostgresError, OSError, TimeoutError):
            pass
        finally:
            if connection is not None:
                await connection.close()
        if not announced:
            print('Waiting for BTC data; run python seed_btc.py --data-dir <BTC directory> on the host.', flush=True)
            announced = True
        await asyncio.sleep(1)


def main():
    mode, *command = sys.argv[1:]
    if '-h' in command or '--help' in command:
        os.execvp(command[0], command)
    if mode in {'setup', 'eval', 'seed'}:
        os.environ['DATABASE_URL'] = database('btc_admin', 'postgres_password')
    if mode in {'setup', 'ai', 'eval'}:
        os.environ['KNOWLEDGE_DATABASE_URL'] = database('btc_reviewer', 'reviewer_password')
    if mode in {'setup', 'worker', 'eval'}:
        os.environ['KNOWLEDGE_WORKER_DATABASE_URL'] = database('btc_worker', 'worker_password')
    if mode == 'setup':
        os.environ['BTC_BACKEND_DATABASE_URL'] = database('btc_backend', 'backend_password')
        if '--allow-policy-build' in command:
            from scripts.prepare_knowledge_tokenizer import TARGET, prepare
            prepare(Path(os.environ['KNOWLEDGE_POLICY_CONFIG_FILE']), TARGET, download=True)
    if mode in {'ai', 'backend'}:
        os.environ['AI_INTERNAL_TOKEN'] = secret('ai_internal_token')
    if mode in {'eval', 'ai'}:
        os.environ['MCP_INTERNAL_TOKEN'] = secret('mcp_internal_token')
    if mode == 'eval':
        if os.environ['MCP_DB_NAME'] != 'telesale_eval_m1':
            raise SystemExit('Eval requires the isolated telesale_eval_m1 project database')
        from app.bootstrap.submission import verify_source

        btc_root = next((arg.split('=', 1)[1] for arg in command if arg.startswith('--btc-root=')), None)
        if btc_root is None and '--btc-root' in command:
            btc_root = next(iter(command[command.index('--btc-root') + 1:]), None)
        if btc_root is None:
            btc_root = os.environ['BTC_DATA_DIR']
        asyncio.run(verify_source(os.environ['DATABASE_URL'], Path(btc_root)))
        os.environ['EVAL_EXPECTED_DATABASE'] = 'telesale_eval_m1'
    if mode == 'backend':
        os.environ['DATABASE_URL'] = database('btc_backend', 'backend_password')
        os.environ['DEMO_JWT_SECRET'] = secret('demo_jwt_secret')
    if mode == 'seed':
        os.environ['DEMO_JWT_SECRET'] = secret('demo_jwt_secret')
        for number in (1, 2):
            os.environ[f'DEMO_USER_{number}_PASSWORD'] = secret(f'demo_user_{number}_password')
    if os.getenv('SUBMISSION_WAIT_FOR_SEED') == '1' and mode in {'ai', 'backend', 'worker'}:
        key = {'ai': 'KNOWLEDGE_DATABASE_URL', 'backend': 'DATABASE_URL',
               'worker': 'KNOWLEDGE_WORKER_DATABASE_URL'}[mode]
        asyncio.run(wait_for_seed(os.environ[key], os.environ['SYSTEM_BOOT_ID']))
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
