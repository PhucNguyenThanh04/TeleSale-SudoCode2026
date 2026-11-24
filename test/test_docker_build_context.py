from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('ignore_file,included', [
    ('Dockerfile.submission.dockerignore', [
        'ai-services/app/main.py', 'ai-services/migrations/runtime.sql',
        'backend/app/voice_main.py', 'backend/migrations/0007_demo_users.sql',
        'frontend/index.html', 'config/policy-runtime.json', 'eval/run_eval.py',
        'speech/__main__.py', 'scripts/btc_container.py',
    ]),
    ('.dockerignore', ['backend/app/voice_main.py', 'backend/requirements.txt', 'frontend/index.html']),
    ('ai-services/.dockerignore', ['app/main.py', 'scripts/container_start.py']),
])
def test_build_context_excludes_local_data_and_preserves_runtime_files(tmp_path, ignore_file, included):
    if not shutil.which('docker'):
        pytest.skip('Docker CLI is required')
    excluded = ['.env', '.git/config', '.venv/lib/probe.txt',
                'ai-services/.venv/lib/probe.txt', 'backend/.venv/lib/probe.txt',
                'speech/test/test_probe.py', 'eval/test_probe.py',
                'speech/asr-benchmark-report.html', 'speech/custom.gguf',
                'speech/custom.safetensors', 'speech/clip.flac',
                'speech/serving/models/probe.onnx',
                'ai-services/app/__pycache__/probe.pyc']
    (tmp_path / '.dockerignore').write_text((ROOT / ignore_file).read_text())
    (tmp_path / 'Dockerfile').write_text('FROM scratch\nCOPY . /\n')
    for name in [*included, *excluded]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    captured = set()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def reply(self, data):
            self.send_response(200)
            self.send_header('API-Version', '1.60')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_HEAD(self):
            self.reply(b'OK')

        def do_GET(self):
            self.reply(json.dumps({'ApiVersion': '1.60', 'MinAPIVersion': '1.44',
                                  'Version': '29.9.2', 'Os': 'linux'}).encode()
                       if 'version' in self.path else b'OK')

        def do_POST(self):
            body = bytearray()
            if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
                while True:
                    size = int(self.rfile.readline().strip().split(b';')[0], 16)
                    if not size:
                        self.rfile.readline()
                        break
                    body.extend(self.rfile.read(size))
                    self.rfile.read(2)
            else:
                body.extend(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if '/build' in self.path:
                with tarfile.open(fileobj=io.BytesIO(body), mode='r:*') as archive:
                    captured.update(member.name for member in archive if member.isfile())
            self.reply(b'{"stream":"Context captured; no image built\\n"}\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        environment = {**os.environ, 'DOCKER_HOST': f'tcp://127.0.0.1:{server.server_port}',
                       'DOCKER_BUILDKIT': '0', 'DOCKER_TLS_VERIFY': ''}
        environment.pop('DOCKER_CONTEXT', None)
        subprocess.run(['docker', 'build', '.'], cwd=tmp_path, env=environment,
                       check=True, capture_output=True, timeout=20)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert set(included) <= captured
    assert not set(excluded) & captured
