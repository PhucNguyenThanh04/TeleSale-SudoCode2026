import os
from pathlib import Path
import subprocess
import sys
import tempfile


BOOTSTRAP = '''
import os, socket
from app.configs import Settings, get_settings
Settings.model_config['env_file'] = None
get_settings.cache_clear()
def offline_connect(*args, **kwargs):
    raise AssertionError('offline tests forbid network connections')
socket.socket.connect = offline_connect
socket.socket.connect_ex = offline_connect
socket.create_connection = offline_connect
'''


def main():
    service = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(service))
    from app.configs import Settings
    env = dict(os.environ)
    for key in list(env):
        if key.casefold() in Settings.model_fields or any(word in key.upper() for word in
                ('API_KEY', 'SECRET', 'PASSWORD', 'DATABASE_URL', 'TOKEN', 'DSN')):
            env.pop(key)
    env.update(APP_ENV='test', LLM_API_KEY='offline-test-key', LLM_MODEL='offline-model',
               DATABASE_URL='postgresql://offline:offline@127.0.0.1/offline', EVAL_RESET_TEST_DB='0', LANGFUSE_ENABLED='false', KNOWLEDGE_ENABLED='false')
    with tempfile.TemporaryDirectory(prefix='harness-offline-') as folder:
        Path(folder, 'sitecustomize.py').write_text(BOOTSTRAP)
        env['PYTHONPATH'] = os.pathsep.join((folder, str(service), str(service.parent)))
        return subprocess.run([sys.executable, '-m', 'pytest', *sys.argv[1:]], env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
