import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'package_btc.py'


def test_archive_delivers_current_source_and_excludes_tracked_secrets_and_local_data(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    files = {
        'README.md': 'old',
        'run_eval.py': 'tracked runner',
        'seed_btc.py': 'seed script',
        'Dockerfile': 'canonical image recipe',
        'docker-compose.yml': 'canonical stack',
        'config/requirements/host.txt': '-r ai.txt',
        'config/requirements/ai.txt': 'AI lock',
        'config/requirements/backend.txt': 'backend lock',
        'config/requirements/asr.txt': 'ASR lock',
        'runtime/policy/.gitkeep': '',
        'runtime/tokenizer/.gitkeep': '',
        'runtime/policy/source.md': 'local initialized policy',
        '.env.example': 'LLM_API_KEY=',
        '.dockerignore': '**/.venv',
        '.env': 'local config',
        'backend/.env': 'private',
        'ai-services/eval_harness/results/trace.jsonl': 'old trace',
        'secrets-submission/postgres_password': 'private',
        'dataset/audio.zip': 'private archive',
        'dataset/README.md': 'dataset',
    }
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    (repo / 'README.md').write_text('updated')
    (repo / 'scripts').mkdir()
    (repo / 'scripts/new.py').write_text('untracked delivery code')
    (repo / 'scripts/link.py').symlink_to('../backend/.env')
    archive = tmp_path / 'btc.zip'
    command = [sys.executable, str(SCRIPT), 'build', '--root', str(repo), '--out', str(archive), '--version', 'test']
    subprocess.run(command, check=True, capture_output=True)
    subprocess.run([sys.executable, str(SCRIPT), 'verify', str(archive)], check=True, capture_output=True)
    with ZipFile(archive) as delivery:
        manifest = json.loads(delivery.read('MANIFEST.json'))
        assert delivery.read('README.md') == b'updated'
        assert delivery.read('scripts/new.py') == b'untracked delivery code'
        assert set(manifest['files']) == {'README.md', 'run_eval.py', 'seed_btc.py', '.env.example', '.dockerignore',
                                          'Dockerfile', 'docker-compose.yml', 'config/requirements/host.txt',
                                          'config/requirements/ai.txt', 'config/requirements/backend.txt',
                                          'config/requirements/asr.txt',
                                          'scripts/new.py', 'dataset/README.md',
                                          'runtime/policy/.gitkeep', 'runtime/tokenizer/.gitkeep'}
        assert manifest['files']['README.md'] == hashlib.sha256(b'updated').hexdigest()
    assert subprocess.run(command, capture_output=True).returncode == 1
    incomplete = tmp_path / 'incomplete.zip'
    command[command.index('--out') + 1] = str(incomplete)
    for missing in ('docker-compose.yml', 'runtime/policy/.gitkeep',
                    'runtime/tokenizer/.gitkeep', 'config/requirements/asr.txt'):
        path = repo / missing
        path.unlink()
        failed = subprocess.run(command, capture_output=True, text=True)
        assert failed.returncode == 1, missing
        assert f'Archive missing required files: {missing}' in failed.stderr
        assert not incomplete.exists()
        path.write_text(files[missing])
