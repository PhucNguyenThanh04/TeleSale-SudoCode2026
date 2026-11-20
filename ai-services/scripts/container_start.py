import os
from pathlib import Path
import sys
import asyncio

from dotenv import dotenv_values


WORKER = {
    'LLM_API_KEY', 'LLM_MODEL', 'LLM_BASE_URL', 'LLM_TIMEOUT_SECONDS',
    'LANGMEM_MODEL', 'LANGMEM_MAX_TOKENS', 'LANGFUSE_PROMPTS_ENABLED',
    'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL',
    'EVAL_DECISION_DIAGNOSTICS',
}


def service_environment(module, path, environment):
    allowed = {'LOG_LEVEL'}
    if module == 'app.mcp_servers.mcp_memory.distiller_worker':
        allowed |= WORKER
    elif module == 'app.mcp_servers.mcp_knowledge.server':
        allowed |= {'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'}
    elif module == 'app.mcp_servers.mcp_memory.server':
        allowed |= {'EVAL_DECISION_DIAGNOSTICS'}
    saved = dotenv_values(path, interpolate=False) if path.is_file() else {}
    selected = {key: value for key, value in saved.items() if key in allowed and value is not None}
    return {**selected, **environment}


def main():
    command = sys.argv[1:]
    if not command:
        raise SystemExit('Container command required')
    module = command[2] if len(command) >= 3 and command[1] == '-m' else ''
    environment = service_environment(module, Path('/config/service.env'), os.environ)
    required = ({'LLM_API_KEY', 'LLM_MODEL'} if module.endswith('.distiller_worker') else
                {'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'} if module.endswith('.mcp_knowledge.server') else set())
    missing = sorted(key for key in required if not environment.get(key, '').strip())
    if missing:
        raise SystemExit('Missing settings in ai-services/.env: ' + ', '.join(missing))
    if environment.get('SYSTEM_BOOT_ID'):
        from app.configs import Settings
        from app.bootstrap.database import require_ready
        from app.mcp_servers.mcp_shared.config import database_url
        settings = Settings(_env_file=None, **{k.lower(): v for k, v in environment.items()})
        asyncio.run(require_ready(database_url(settings), environment['SYSTEM_BOOT_ID']))
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()
