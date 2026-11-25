import asyncio
import os
import sys

from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url
from scripts.btc_container import wait_for_seed


def main():
    command = sys.argv[1:]
    if not command:
        raise SystemExit('Container command required')
    module = command[2] if len(command) >= 3 and command[1] == '-m' else ''
    required = ({'LLM_API_KEY', 'LLM_MODEL'} if module.endswith('.distiller_worker') else
                {'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'} if module.endswith('.mcp_knowledge.server') else set())
    missing = sorted(key for key in required if not os.environ.get(key, '').strip())
    if missing:
        raise SystemExit('Missing environment settings: ' + ', '.join(missing))
    settings = Settings(_env_file=None)
    asyncio.run(wait_for_seed(database_url(settings), os.environ['SYSTEM_BOOT_ID']))
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
