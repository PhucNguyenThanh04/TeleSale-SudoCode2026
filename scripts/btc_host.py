import asyncio
import os
from pathlib import Path
import sys
from urllib.parse import quote

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ConfigurationError(ValueError):
    pass


def configuration(root, source=None):
    from dotenv import dotenv_values

    root = Path(root).resolve()
    path = root / '.env'
    if not path.is_file():
        raise ConfigurationError('Place the completed .env in the repository root first.')
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None}
    values.update({key: os.environ[key] for key in values if key in os.environ})
    required = ['POSTGRES_PASSWORD', 'REVIEWER_PASSWORD', 'WORKER_PASSWORD', 'BACKEND_PASSWORD',
                'LLM_API_KEY', 'LLM_MODEL', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN',
                'MCP_INTERNAL_TOKEN', 'AI_INTERNAL_TOKEN', 'DEMO_JWT_SECRET', 'DEMO_USER_1_PASSWORD', 'DEMO_USER_2_PASSWORD',
                *['MCP_' + name.upper() + '_PASSWORD' for name in ('catalog', 'order', 'memory', 'knowledge')]]
    missing = [key for key in required if not values.get(key, '').strip()]
    if missing:
        raise ConfigurationError('Missing .env settings: ' + ', '.join(missing))
    defaults = {'SUBMISSION_POSTGRES_PORT': '15432', 'SUBMISSION_QDRANT_PORT': '16333',
                'SUBMISSION_AI_PORT': '18001', 'DEMO_PORT': '8000',
                **{'SUBMISSION_MCP_' + name.upper() + '_PORT': str(18011 + offset)
                   for offset, name in enumerate(('catalog', 'order', 'memory', 'knowledge'))}}
    for key, default in defaults.items():
        values[key] = values.get(key) or default
        if not values[key].isdigit() or not 1 <= int(values[key]) <= 65535:
            raise ConfigurationError(key + ' must be a port between 1 and 65535')
    for key, default in {'LLM_BASE_URL': 'https://api.openai.com/v1', 'LLM_TIMEOUT_SECONDS': '30',
                         'CLOUDFLARE_API_BASE_URL': 'https://api.cloudflare.com/client/v4'}.items():
        values[key] = values.get(key) or default
    database = values.get('SUBMISSION_DATABASE') or 'telesale_eval_m1'
    if database != 'telesale_eval_m1':
        raise ConfigurationError('Submission scripts require the dedicated telesale_eval_m1 database')
    source = Path(source if source is not None else values.get('BTC_ROOT') or '../BTC-Data-Vong1-TEAMS')
    source = (root / source).resolve()
    port = values['SUBMISSION_POSTGRES_PORT']
    def dsn(role, key):
        return f'postgresql+asyncpg://{role}:{quote(values[key], safe="")}@127.0.0.1:{port}/{database}'
    values.update(DATABASE_URL=dsn('btc_admin', 'POSTGRES_PASSWORD'),
        KNOWLEDGE_DATABASE_URL=dsn('btc_reviewer', 'REVIEWER_PASSWORD'),
        KNOWLEDGE_WORKER_DATABASE_URL=dsn('btc_worker', 'WORKER_PASSWORD'),
        BTC_BACKEND_DATABASE_URL=dsn('btc_backend', 'BACKEND_PASSWORD'),
        APP_ENV='development', SYSTEM_BOOT_ID='btc-submission-v1', MCP_DB_NAME=database,
        BTC_DATA_DIR=str(source), QDRANT_URL='http://127.0.0.1:' + values['SUBMISSION_QDRANT_PORT'],
        KNOWLEDGE_POLICY_SOURCE_DIR=str(root / 'runtime/policy'),
        KNOWLEDGE_POLICY_CONFIG_FILE=str(root / 'runtime/policy-runtime.host.json'),
        AI_ENV_FILE=str(path), EVAL_EXPECTED_DATABASE=database,
        LLM_MAX_TOKENS='1024', AGENT_MAX_TOOL_CALLS='8', AGENT_GUARDRAILS_ENABLED='true',
        KNOWLEDGE_ENABLED='true', LANGFUSE_ENABLED='false', LANGFUSE_PROMPTS_ENABLED='false',
        LANGFUSE_CAPTURE_CONTENT='false', BTC_SUBMISSION_DEMO_PORT=values['DEMO_PORT'],
        PYTHONPATH=str(root / 'ai-services') + os.pathsep + str(root))
    for name in ('catalog', 'order', 'memory', 'knowledge'):
        values['MCP_' + name.upper() + '_URL'] = ('http://127.0.0.1:'
            + values['SUBMISSION_MCP_' + name.upper() + '_PORT'] + '/mcp')
    return values


def verify_seed(root, values):
    source = Path(values['BTC_DATA_DIR'])
    if not source.is_dir():
        raise ConfigurationError('BTC_ROOT must point to the BTC data directory used by seed_btc.py.')
    if not Path(values['KNOWLEDGE_POLICY_CONFIG_FILE']).is_file():
        raise ConfigurationError('Run python seed_btc.py --data-dir <BTC directory> first.')
    sys.path.insert(0, str(Path(root) / 'ai-services'))
    from app.bootstrap.submission import verify_source

    try:
        asyncio.run(verify_source(values['DATABASE_URL'], source))
    except Exception as exc:
        raise ConfigurationError('Seed verification failed (' + type(exc).__name__
            + '). Check the running PostgreSQL service, BTC_ROOT and run seed_btc.py first.') from None
