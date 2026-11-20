import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from app.bootstrap.database import BootDatabase, BootError, require_ready
from app.bootstrap.policy import capture_base, initialize_base
from app.configs import get_settings
from app.knowledge.config import configured_url, qdrant_url
from app.knowledge.policy.source import default_metadata
from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
from app.mcp_servers.mcp_shared.config import database_url

ROOT = Path(__file__).resolve().parents[2]
MCP = ('mcp-catalog', 'mcp-order', 'mcp-memory', 'mcp-knowledge', 'langmem-worker')


class StartupError(ValueError):
    pass


async def fingerprint_btc_source(dsn):
    from eval_harness.seed_fingerprint import fingerprint_btc_source as fingerprint
    try:
        return await fingerprint(dsn)
    except ValueError:
        raise StartupError('Import the BTC source tables before starting a fresh demo/eval') from None


def run(command, *, env=None, cwd=ROOT):
    subprocess.run([str(x) for x in command], cwd=cwd, env=env, check=True)


def compose(*args):
    prefix = ['sudo', '--preserve-env=SYSTEM_BOOT_ID', 'docker'] if os.getenv('SYSTEM_SUDO_DOCKER') == '1' else ['docker']
    run([*prefix, 'compose', '--env-file', ROOT/'.env', '--env-file', ROOT/'ai-services/.env', *args])


def backend_values():
    return {**dotenv_values(ROOT/'backend/.env'), **os.environ}


def backend_environment(env):
    return {**os.environ, **env, 'PYTHONPATH': str(ROOT/'backend')}


def check_configuration(settings, mode):
    if settings.app_env == 'production' or not settings.database_url:
        raise StartupError('Managed fresh startup requires a non-production administrative DATABASE_URL')
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        raise StartupError('Cloudflare policy embedding configuration is required before startup')
    if mode == 'demo' and not settings.ai_internal_token:
        raise StartupError('AI_INTERNAL_TOKEN required for the managed demo')
    if mode == 'demo' and backend_values().get('AI_INTERNAL_TOKEN') != settings.ai_internal_token.get_secret_value():
        raise StartupError('Backend and AI AI_INTERNAL_TOKEN settings must match')
    if mode == 'knowledge-eval' and (not settings.knowledge_enabled or not settings.agent_guardrails_enabled):
        raise StartupError('Knowledge experiment requires KNOWLEDGE_ENABLED=true and AGENT_GUARDRAILS_ENABLED=true')
    for key in ('KNOWLEDGE_DATABASE_URL', 'KNOWLEDGE_WORKER_DATABASE_URL'):
        if not configured_url(key): raise StartupError(key + ' required')
    if not settings.knowledge_policy_source_dir or not settings.knowledge_policy_source_dir.is_dir():
        raise StartupError('KNOWLEDGE_POLICY_SOURCE_DIR must identify the imported BTC policy directory')
    if not settings.knowledge_policy_config_file or not settings.knowledge_policy_config_file.is_file():
        raise StartupError('KNOWLEDGE_POLICY_CONFIG_FILE required')
    if mode == 'demo':
        code = ('from app.seed_demo_users import SeedSettings\n'
                'from pydantic import ValidationError\n'
                'try:\n'
                ' config = SeedSettings()\n'
                ' if not config.demo_jwt_secret or not config.ai_internal_token:\n'
                '  raise SystemExit("DEMO_JWT_SECRET and AI_INTERNAL_TOKEN required in backend configuration")\n'
                'except ValidationError as e:\n'
                ' print("Invalid demo settings: " + ", ".join(".".join(map(str,x["loc"])) for x in e.errors()))\n'
                ' raise SystemExit(1)\n')
        run([ROOT/'backend/.venv/bin/python', '-c', code], env=backend_environment({}))


def check_host_ports(settings, mode):
    for port in (settings.port, 8000):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise StartupError('Stop the previous AI/gateway server before starting a fresh demo')


def wait_ports(ports, children=(), timeout=45):
    deadline = time.monotonic() + timeout
    pending = set(ports)
    while pending:
        if any(child.poll() is not None for child in children):
            raise RuntimeError('A server exited during startup')
        for port in list(pending):
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(('127.0.0.1', port)) == 0: pending.remove(port)
        if pending and time.monotonic() >= deadline:
            raise RuntimeError('Timed out waiting for managed service ports')
        if pending: time.sleep(0.2)


def wait_services(settings):
    wait_ports([getattr(settings, f'mcp_{name}_port') for name in ('catalog', 'order', 'memory', 'knowledge')])


async def pg_connect(dsn):
    deadline = time.monotonic() + 30
    while True:
        try:
            return await asyncpg.connect(dsn.replace('postgresql+asyncpg://', 'postgresql://', 1), timeout=2)
        except (OSError, asyncpg.CannotConnectNowError):
            if time.monotonic() >= deadline: raise
            await asyncio.sleep(0.2)


async def verify_backend_database(settings, expected, env):
    dsn = database_url(settings)
    admin = make_url(dsn)
    if admin.database != expected: raise StartupError('AI database differs from --expected-database')
    targets = [configured_url('KNOWLEDGE_DATABASE_URL'), configured_url('KNOWLEDGE_WORKER_DATABASE_URL'),
               backend_values().get('DATABASE_URL')]
    def host(url):
        return 'local' if url.host in {'localhost', '127.0.0.1', '::1'} else url.host
    for value in targets:
        if not value: continue
        target = make_url(value)
        if (target.database != expected or host(target) != host(admin)
                or (target.port or 5432) != (admin.port or 5432)):
            raise StartupError('Backend, AI and knowledge roles must point to the same database server')
    conn = await pg_connect(dsn)
    try:
        if await conn.fetchval('SELECT current_database()') != expected:
            raise StartupError('Connected database differs from --expected-database')
    finally:
        await conn.close()


async def setup_store(dsn):
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from app.mcp_servers.mcp_memory.repos.langmem_projection import store_dsn
    async with AsyncPostgresStore.from_conn_string(store_dsn(dsn), index=None) as store:
        await store.setup()


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


async def setup_logins(boot, settings):
    conn = boot.connection
    for dsn, group in [(configured_url('KNOWLEDGE_DATABASE_URL'), 'knowledge_reviewer'),
                       (configured_url('KNOWLEDGE_WORKER_DATABASE_URL'), 'knowledge_worker'),
                       (backend_values().get('DATABASE_URL'), 'knowledge_backend')]:
        if not dsn: continue
        url = make_url(dsn)
        if not url.username: raise StartupError('Application DB login is required')
        role = quoted(url.username)
        if not await conn.fetchval('SELECT 1 FROM pg_roles WHERE rolname=$1', url.username):
            if not url.password: raise StartupError('A password is required to initialize an application DB login')
            sql = await conn.fetchval('SELECT format(\'CREATE ROLE %I LOGIN PASSWORD %L\', $1::text, $2::text)', url.username, url.password)
            await conn.execute(sql)
        if url.username != await conn.fetchval('SELECT current_user'):
            await conn.execute(f'GRANT {group} TO {role}')
        await conn.execute(f'GRANT CONNECT ON DATABASE {quoted(boot.expected_database)} TO {role}')
        await conn.execute(f'''GRANT USAGE ON SCHEMA system_boot TO {role};
            GRANT SELECT ON system_boot.current TO {role};''')
        if group == 'knowledge_backend':
            await conn.execute(f'''GRANT USAGE ON SCHEMA runtime,btc_source,system_boot TO {role};
                GRANT SELECT ON ALL TABLES IN SCHEMA btc_source TO {role};
                GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA runtime TO {role};
                GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA runtime TO {role};
                GRANT SELECT ON system_boot.current TO {role};''')


async def setup_policy(dsn, settings, cache, old_collections):
    from qdrant_client import AsyncQdrantClient
    from app.mcp_servers.mcp_knowledge.config import load_policy_config
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    config = load_policy_config(settings)
    encoder = PolicyEncoder(config)
    client = AsyncQdrantClient(url=qdrant_url(), timeout=config.dependency_timeout_seconds)
    repo = PolicyRepository(dsn)
    actor = backend_values().get('KNOWLEDGE_REVIEWER_ID') or 'local-reviewer'
    try:
        if cache is None:
            for name in old_collections:
                if name.startswith('policy_') and await client.collection_exists(name):
                    await client.delete_collection(name)
        async with repo.transaction() as tx:
            for name in {'system-bootstrap', actor}:
                await tx.put('permissions', name, {'id': name, 'permissions': ['knowledge_review']})
        release = await initialize_base(repo, encoder, HybridPolicyIndex(client),
            source_dir=settings.knowledge_policy_source_dir, metadata=default_metadata(),
            actor_id='system-bootstrap', cache=cache)
        keep = release['manifest']['collection']
        for name in old_collections:
            if name != keep and name.startswith('policy_') and await client.collection_exists(name):
                await client.delete_collection(name)
    finally:
        await encoder.close(); await client.close(); await repo.close()


def seed_accounts(env):
    run([ROOT/'backend/.venv/bin/python', '-m', 'app.seed_demo_users'], env=backend_environment(env))


def serve(args, settings, env):
    children = []
    try:
        if args.mode == 'demo':
            commands = [(sys.executable, '-m', 'app'),
                        (sys.executable, '-m', 'app.knowledge.worker'),
                        (ROOT/'backend/.venv/bin/python', '-m', 'uvicorn', 'app.voice_main:app',
                         '--app-dir', str(ROOT/'backend'), '--host', '127.0.0.1', '--port', '8000')]
            for command in commands:
                child_env = backend_environment(env) if str(command[0]).startswith(str(ROOT/'backend')) else env
                children.append(subprocess.Popen([str(x) for x in command], cwd=ROOT, env=child_env))
            wait_ports([settings.port, 8000], children)
        if args.mode != 'demo':
            module = 'eval_harness.knowledge_triplet' if args.mode == 'knowledge-eval' else 'eval_harness.run_official'
            command = list(args.command)
            if command[:1] == ['--']: command.pop(0)
            if args.resume:
                command += ['--resume', str(args.resume)]
            else:
                command += ['--expected-database', args.expected_database]
            run([sys.executable, '-m', module, *command], env=env)
            return
        if children:
            print('Fresh demo ready: http://127.0.0.1:8000/chat', flush=True)
            while True:
                if any(p.poll() is not None for p in children):
                    raise RuntimeError('A managed server exited; stop this boot and inspect its logs')
                time.sleep(0.2)
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


async def start(args, settings, env):
    if args.mode == 'eval':
        serve(args, settings, env)
        return
    check_configuration(settings, args.mode)
    if args.resume:
        await require_ready(database_url(settings), env['SYSTEM_BOOT_ID'])
        env['SYSTEM_STACK_OWNER'] = '1'
        compose('up', '-d', *MCP)
        wait_services(settings)
        serve(args, settings, env)
        return
    check_host_ports(settings, args.mode)
    env['SYSTEM_STACK_OWNER'] = '1'
    compose('stop', *MCP)
    compose('up', '-d', 'postgres', 'redis', 'qdrant')
    await verify_backend_database(settings, args.expected_database, env)
    dsn = database_url(settings)
    before = await fingerprint_btc_source(dsn)
    async with BootDatabase(dsn, args.expected_database, env['SYSTEM_BOOT_ID'], app_env=settings.app_env) as boot:
        if not boot.ready:
            cache, old_collections = None, []
            if await boot.connection.fetchval("SELECT to_regclass('knowledge.releases')"):
                repo = PolicyRepository(dsn)
                try:
                    cache = await capture_base(repo)
                    async with repo.transaction() as tx:
                        old_collections = [r['manifest']['collection'] for r in await tx.rows('releases')
                                           if r.get('manifest', {}).get('collection')]
                finally:
                    await repo.close()
            await boot.create_fresh_schema()
            print('[startup] backend/AI operational schemas recreated; BTC retained', flush=True)
            await setup_store(dsn)
            await setup_logins(boot, settings)
            compose('run', '--rm', 'mcp-db-roles')
            if args.mode == 'demo': seed_accounts(env)
            print('[startup] restoring BTC-only policy; no approved gap knowledge is retained', flush=True)
            await setup_policy(dsn, settings, cache, old_collections)
            if before != await fingerprint_btc_source(dsn):
                raise StartupError('BTC source changed during managed startup')
            await boot.mark_ready()
            print('[startup] shared boot ready: ' + env['SYSTEM_BOOT_ID'], flush=True)
    compose('exec', '-T', 'redis', 'redis-cli', 'FLUSHDB')
    compose('up', '-d', '--build', *MCP)
    wait_services(settings)
    serve(args, settings, env)


def startup_lock_path():
    return ROOT/'.system-start.lock'


def main():
    p = argparse.ArgumentParser(description='Manage fresh demos; ordinary eval uses the existing services and runner reset.')
    p.add_argument('mode', choices=['demo', 'eval', 'knowledge-eval'])
    p.add_argument('--expected-database', required=True)
    p.add_argument('--resume', type=Path)
    p.add_argument('--sudo-docker', action='store_true', help='Use sudo only for Docker commands')
    args, command = p.parse_known_args()
    args.command = command
    if '--manual-review' in command:
        p.error('Use ordinary eval, then run_knowledge_eval.py --base-run RUN after frontend review; --manual-review was removed')
    if args.mode == 'knowledge-eval' and not args.resume:
        plan_parser = argparse.ArgumentParser(add_help=False)
        review_mode = plan_parser.add_mutually_exclusive_group()
        review_mode.add_argument('--approval-plan', type=Path)
        review_mode.add_argument('--auto-review', action='store_true')
        plan_args, _ = plan_parser.parse_known_args(command[1:] if command[:1] == ['--'] else command)
        if plan_args.approval_plan:
            try:
                from eval_harness.knowledge_auto_review import validate_plan
                validate_plan(json.loads(plan_args.approval_plan.read_text(encoding='utf-8')))
            except Exception:
                p.error('--approval-plan must point to an existing valid pre-reviewed JSON plan; no startup/reset performed')
    if any(item == '--resume' or item.startswith('--resume=') for item in command):
        p.error('Put --resume before --; refusing a fresh reset of an existing experiment')
    if args.resume and args.mode != 'knowledge-eval': p.error('--resume is only valid for knowledge-eval')
    if command[:1] == ['--']: command = command[1:]
    args.command = command
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT/'ai-services'), str(ROOT)]))
    env.pop('SYSTEM_STACK_OWNER', None)
    if args.mode == 'eval':
        try:
            asyncio.run(start(args, None, env))
        except KeyboardInterrupt:
            pass
        except subprocess.CalledProcessError as exc:
            raise SystemExit(exc.returncode) from None
        return
    settings = get_settings()
    env['KNOWLEDGE_RELEASE_ID'] = ''
    if args.resume:
        state = json.loads((args.resume/'experiment.json').read_text())
        boot_id = state.get('system_boot_id')
        if not boot_id: raise SystemExit('This experiment has no managed boot ID; do not reset it to resume')
    else:
        boot_id = str(uuid4())
    env['SYSTEM_BOOT_ID'] = boot_id
    os.environ['SYSTEM_BOOT_ID'] = boot_id
    os.environ['KNOWLEDGE_RELEASE_ID'] = ''
    if args.sudo_docker: os.environ['SYSTEM_SUDO_DOCKER'] = '1'
    lock = startup_lock_path()
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another managed demo/eval is already running') from None
        try:
            asyncio.run(start(args, settings, env))
        except KeyboardInterrupt:
            pass
        except subprocess.CalledProcessError as exc:
            raise SystemExit(exc.returncode) from None
        except Exception as exc:
            reason = str(exc) if isinstance(exc, (StartupError, BootError)) else type(exc).__name__
            raise SystemExit(f'Fresh startup stopped: {reason}. No server will be started with a partial boot.') from None
        finally:
            if env.get('SYSTEM_STACK_OWNER') == '1':
                try: compose('stop', *MCP)
                except subprocess.CalledProcessError:
                    print('Could not stop managed MCP containers; inspect Docker logs.', file=sys.stderr)


if __name__ == '__main__':
    main()
