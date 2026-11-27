import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = {'postgres', 'qdrant', 'redis', 'mcp-catalog', 'mcp-order', 'mcp-memory',
        'mcp-knowledge', 'langmem-worker', 'knowledge-worker', 'ai', 'backend', 'speech', 'vieneu'}


def configuration(tmp_path, profile=None, gpu=False):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose CLI is required')
    shutil.copyfile(ROOT / 'docker-compose.yml', tmp_path / 'docker-compose.yml')
    text = (ROOT / '.env.example').read_text()
    text += '\nLLM_API_KEY=offline-key\nCLOUDFLARE_ACCOUNT_ID=offline-account\nCLOUDFLARE_API_TOKEN=offline-token\n'
    (tmp_path / '.env').write_text(text)
    command = ['docker', 'compose']
    if gpu:
        command += ['-f', str(tmp_path / 'docker-compose.yml'),
                    '-f', str(ROOT / 'config/compose.gpu.yml')]
    if profile:
        command += ['--profile', profile]
    completed = subprocess.run([*command, 'config', '--format', 'json'],
        cwd=tmp_path, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_plain_compose_up_contains_all_servers_but_no_seed_or_eval(tmp_path):
    config = configuration(tmp_path)
    services = config['services']
    assert set(services) == CORE
    assert config['name'] == 'telesale-btc'
    for name in CORE - {'postgres', 'qdrant', 'redis', 'speech', 'vieneu'}:
        assert services[name]['environment']['SUBMISSION_WAIT_FOR_SEED'] == '1'
        assert not {'setup', 'mcp-db-roles', 'seed'} & services[name].get('depends_on', {}).keys()
    assert services['backend']['depends_on']['ai']['condition'] == 'service_started'
    assert all(value['condition'] == 'service_started'
               for value in services['ai']['depends_on'].values())
    assert {name for name, service in services.items() if service.get('ports')} == CORE - {'redis', 'langmem-worker', 'knowledge-worker', 'vieneu'}
    for service in services.values():
        assert all(port['host_ip'] == '127.0.0.1' for port in service.get('ports', []))
    for name in ('mcp-catalog', 'mcp-order', 'mcp-memory', 'mcp-knowledge', 'ai', 'backend'):
        assert services[name]['healthcheck']['start_period'] == '24h0m0s'


def test_root_compose_is_self_contained(tmp_path, monkeypatch):
    monkeypatch.delenv('COMPOSE_FILE', raising=False)
    monkeypatch.delenv('COMPOSE_PROJECT_NAME', raising=False)
    config = configuration(tmp_path)
    assert set(config['services']) == CORE
    assert config['name'] == 'telesale-btc'
    assert config['services']['postgres']['environment']['POSTGRES_USER'] == 'btc_admin'
    assert all(service['build']['dockerfile'] == 'Dockerfile'
               for service in config['services'].values() if service.get('build'))


def test_servers_do_not_mount_or_require_the_host_btc_directory(tmp_path):
    config = configuration(tmp_path)
    services = config['services']
    for service in services.values():
        assert 'BTC_DATA_DIR' not in service.get('environment', {})
        assert all(mount['target'] != '/btc' for mount in service.get('volumes', []))
    policy = next(mount for mount in services['ai']['volumes']
                  if mount['target'] == '/policy-source')
    assert policy['type'] == 'bind' and policy['read_only']
    assert policy['source'] == str(tmp_path / 'runtime/policy')
    assert (ROOT / 'runtime/policy/.gitkeep').is_file()
    assert (ROOT / 'runtime/tokenizer/.gitkeep').is_file()
    assert services['ai']['environment']['KNOWLEDGE_POLICY_SOURCE_DIR'] == '/policy-source'
    assert not (tmp_path.parent / 'BTC-Data-Vong1-TEAMS').exists()


def test_shared_images_are_built_once_and_never_pulled_from_a_registry(tmp_path):
    services = configuration(tmp_path)['services']
    assert {name for name, service in services.items() if service.get('build')} == {'ai', 'backend', 'speech'}
    for name in CORE - {'postgres', 'qdrant', 'redis'}:
        assert services[name]['pull_policy'] == 'never'
    assert services['ai']['build']['target'] == 'ai'
    assert services['backend']['build']['target'] == 'backend'
    assert services['speech']['build']['target'] == 'speech'
    assert services['speech']['image'] == services['vieneu']['image']


def test_voice_services_connect_inside_compose_and_keep_downloaded_models(tmp_path):
    config = configuration(tmp_path)
    services = config['services']
    backend = services['backend']
    speech = services['speech']
    assert backend['environment']['SPEECH_HTTP_URL'] == 'http://speech:18110'
    assert backend['environment']['SPEECH_LISTEN_URL'] == 'ws://speech:18110/v1/speech/listen'
    assert backend['depends_on']['speech']['condition'] == 'service_healthy'
    assert speech['environment']['VIENEU_URL'] == 'http://vieneu:18111'
    assert speech['environment']['WEB_URL'] == 'http://backend:8000'
    assert speech['depends_on']['vieneu']['condition'] == 'service_healthy'
    for name in ('speech', 'vieneu'):
        service = services[name]
        assert service['restart'] == 'unless-stopped'
        assert not service.get('profiles')
        assert service['environment']['SPEECH_ASR_PROVIDER'] == 'cpu'
        assert service['environment']['SPEECH_VAD_PROVIDER'] == 'cpu'
        assert service['environment']['SPEECH_TTS_PROVIDER'] == 'cpu'
        for setting in ('SPEECH_MODEL_DIR', 'HF_HOME'):
            mount = next(mount for mount in service['volumes']
                         if mount['target'] == service['environment'][setting])
            assert mount['type'] == 'volume'
            assert mount['source'] in config['volumes']
        assert service['healthcheck']['test'][0] == 'CMD'
    assert not services['vieneu'].get('ports')


def test_gpu_configuration_builds_one_cuda_image_and_exposes_gpu_to_both_servers(tmp_path):
    services = configuration(tmp_path, gpu=True)['services']
    assert services['speech']['build']['target'] == 'speech-gpu'
    assert services['speech']['image'] == services['vieneu']['image']
    assert services['speech']['image'] != configuration(tmp_path)['services']['speech']['image']
    assert not services['vieneu'].get('build')
    for name in ('speech', 'vieneu'):
        service = services[name]
        for setting in ('SPEECH_ASR_PROVIDER', 'SPEECH_VAD_PROVIDER', 'SPEECH_TTS_PROVIDER'):
            assert service['environment'][setting] == 'cuda'
        device = service['deploy']['resources']['reservations']['devices'][0]
        assert device == {'driver': 'nvidia', 'count': 1, 'capabilities': ['gpu']}
    assert services['speech']['environment']['VIENEU_URL'] == 'http://vieneu:18111'
    assert services['backend']['environment']['SPEECH_HTTP_URL'] == 'http://speech:18110'


def test_host_seed_connects_to_loopback_ports_without_a_compose_job(tmp_path):
    services = configuration(tmp_path, 'seed')['services']
    assert set(services) == CORE
    assert services['postgres']['ports'][0]['published'] == '15432'
    assert services['qdrant']['ports'][0]['published'] == '16333'
    assert not (ROOT / 'seed_btc.sh').exists()


def test_all_compose_profiles_contain_servers_only(tmp_path):
    services = configuration(tmp_path, '*')['services']
    assert set(services) == CORE
    assert all(not service.get('profiles') for service in services.values())
    for service in services.values():
        assert all(mount['target'] not in {'/btc', '/scenarios', '/results', '/audio-dataset'}
                   for mount in service.get('volumes', []))
