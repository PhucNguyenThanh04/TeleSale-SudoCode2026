from pathlib import Path
import yaml


def compose_services():
    path = Path(__file__).resolve().parents[2] / 'compose.dev.yml'
    return yaml.safe_load(path.read_text())['services']


def test_all_four_mcp_servers_share_default_compose_lifecycle():
    services = compose_services()
    for name in ('catalog', 'order', 'memory', 'knowledge'):
        service = services[f'mcp-{name}']
        assert not service.get('profiles'), f'mcp-{name} must start without an optional profile'
        assert service['restart'] == 'unless-stopped'
        assert service['command'] == ['python', '-m', f'app.mcp_servers.mcp_{name}.server']
        assert service['depends_on']['mcp-db-roles']['condition'] == 'service_completed_successfully'
        assert service['environment']['MCP_DB_USER'] == f'mcp_{name}'
        assert f'mcp_{name}_password' in service['secrets']
        assert 'mcp_internal_token' in service['secrets']
        assert 'telesale_network' in service['networks']


def test_knowledge_compose_cpu_and_explicit_cloudflare_env():
    assert compose_services()['qdrant']['image'] == 'qdrant/qdrant:v1.19.1'
    knowledge = compose_services()['mcp-knowledge']
    mounts = {mount['target']: mount for mount in knowledge['volumes']}
    assert set(mounts) == {'/config/policy-runtime.json', '/config/service.env'}
    assert mounts['/config/policy-runtime.json']['bind']['create_host_path'] is False
    assert mounts['/config/policy-runtime.json']['read_only'] is True
    assert 'deploy' not in knowledge
    assert 'CLOUDFLARE_ACCOUNT_ID' not in knowledge['environment']
    assert 'CLOUDFLARE_API_TOKEN' not in knowledge['environment']
    assert not knowledge.get('env_file')
    root=Path(__file__).resolve().parents[1]
    docker=(root/'Dockerfile').read_text()
    requirements=(root/'requirements.txt').read_text().casefold()
    assert 'ARG BASE_IMAGE=python:3.12-slim' in docker
    assert 'nvidia/cuda' not in docker and 'torch==' not in docker
    assert 'flagembedding' not in requirements and 'tokenizers==' in requirements


def test_all_ai_services_use_shared_dockerfile_and_requirements():
    services = compose_services()
    root = Path(__file__).resolve().parents[1]
    shared_build = services['mcp-catalog']['build']
    assert shared_build == {
        'context': './ai-services',
        'args': {'BASE_IMAGE': '${AI_BASE_IMAGE:-python:3.12-slim}'},
    }
    for name in ('mcp-order', 'mcp-memory', 'mcp-knowledge', 'langmem-worker'):
        assert services[name]['build'] == shared_build
    assert not (root/'Dockerfile.knowledge').exists()
    assert not (root/'requirements-knowledge.txt').exists()


def test_shared_dockerfile_recovers_slow_dependency_downloads():
    root = Path(__file__).resolve().parents[1]
    recipe = (root/'Dockerfile').read_text()
    assert recipe.startswith('# syntax=docker/dockerfile:1\n')
    assert 'PIP_DEFAULT_TIMEOUT=120' in recipe
    assert 'PIP_RETRIES=5' in recipe
    assert 'PIP_RESUME_RETRIES=5' in recipe
    assert '--mount=type=cache' in recipe
    assert 'target=/root/.cache/pip' in recipe
    assert '--no-cache-dir' not in recipe
    assert recipe.index('pip install --upgrade pip==25.2') < recipe.index('pip install -r requirements.txt')


def test_decision_diagnostics_flag_reaches_memory_and_worker_once():
    services = compose_services()
    for name in ('mcp-memory', 'langmem-worker'):
        assert 'EVAL_DECISION_DIAGNOSTICS' not in services[name]['environment']
        assert any(m['target'] == '/config/service.env' and m['read_only'] for m in services[name]['volumes'])
    raw = (Path(__file__).resolve().parents[2] / 'compose.dev.yml').read_text()
    assert raw.count('      EVAL_DECISION_DIAGNOSTICS:') == 0
