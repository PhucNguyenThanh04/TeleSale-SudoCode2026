"""Safe defaults even when focused harness tests are run directly."""
import os
from pathlib import Path
import socket
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.configs import Settings, get_settings

Settings.model_config['env_file'] = None
for key in list(os.environ):
    if key.casefold() in Settings.model_fields:
        os.environ.pop(key)
os.environ.update(LLM_API_KEY='offline-test-key', LLM_MODEL='offline-model',
                  APP_ENV='test', DATABASE_URL='postgresql://offline:offline@127.0.0.1/offline', EVAL_RESET_TEST_DB='0')
get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('offline tests forbid network connections')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    yield
    get_settings.cache_clear()


@pytest.fixture
def offline_settings():
    return Settings(_env_file=None, llm_api_key='offline-test-key', llm_model='offline-model')


@pytest.fixture
def fake_release():
    return {'release_id': 'btc-only', 'manifest_hash': 'btc-only'}
