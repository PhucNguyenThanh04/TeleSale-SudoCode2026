"""Deployment contract for the four default MCP Compose services."""
from pathlib import Path
import yaml


def compose_services():
    path = Path(__file__).resolve().parents[2] / 'docker-compose.yml'
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
    assert set(mounts) == {'/config/policy-runtime.json'}
    assert mounts['/config/policy-runtime.json']['bind']['create_host_path'] is False
    assert mounts['/config/policy-runtime.json']['read_only'] is True
    assert 'deploy' not in knowledge
    assert knowledge['environment']['CLOUDFLARE_ACCOUNT_ID'].startswith('${CLOUDFLARE_ACCOUNT_ID:')
    assert knowledge['environment']['CLOUDFLARE_API_TOKEN'].startswith('${CLOUDFLARE_API_TOKEN:')
    assert not knowledge.get('env_file')
    root=Path(__file__).resolve().parents[1]
    docker=(root/'Dockerfile.knowledge').read_text()
    requirements=(root/'requirements-knowledge.txt').read_text().casefold()
    assert 'FROM python:3.12-slim' in docker
    assert 'nvidia/cuda' not in docker and 'torch==' not in docker
    assert 'flagembedding' not in requirements and 'tokenizers==' in requirements


def test_both_dockerfiles_recover_slow_dependency_downloads():
    root = Path(__file__).resolve().parents[1]
    for name in ('Dockerfile', 'Dockerfile.knowledge'):
        recipe = (root/name).read_text()
        assert recipe.startswith('# syntax=docker/dockerfile:1\n')
        assert 'PIP_DEFAULT_TIMEOUT=120' in recipe
        assert 'PIP_RETRIES=5' in recipe
        assert 'PIP_RESUME_RETRIES=5' in recipe
        assert '--mount=type=cache' in recipe
        assert 'target=/root/.cache/pip' in recipe
        assert '--no-cache-dir' not in recipe
        assert recipe.index('pip install --upgrade pip==25.2') < recipe.index('pip install -r requirements.txt')
