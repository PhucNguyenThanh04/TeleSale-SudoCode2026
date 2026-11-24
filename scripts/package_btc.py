import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'ai-services', 'backend', 'config', 'dataloader_offline', 'dataset',
               'docs', 'eval', 'frontend', 'scripts', 'speech', 'test'}
SOURCE_ROOT = {'AGENTS.md', 'README.md', 'START_HERE.md', 'Dockerfile.submission', 'Dockerfile.submission.dockerignore',
               'compose.submission.yml', 'docker-compose.yml', 'pyproject.toml', 'uv.lock',
               'run_eval.py', 'run_submission.py', 'run_knowledge_eval.py', 'run_system.py', '.gitignore',
               '.gitattributes', '.python-version', '.env.example', '.env.submission.example'}
EXCLUDED_DIRS = {'__pycache__', 'cache', 'node_modules', 'storage', 'secrets', 'secrets-submission',
                 'artifacts', 'outputs', 'results', 'results-submission', 'runs', 'graphify-out',
                 'models', 'postgres_data', 'traces'}
EXCLUDED_SUFFIXES = {'.bin', '.db', '.gguf', '.key', '.m4a', '.mp3', '.mp4', '.ogg', '.onnx', '.pem',
                     '.pfx', '.pt', '.pyc', '.safetensors', '.sqlite', '.wav', '.zip'}


def source_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != name or '\\' in name or not path.parts:
        return False
    if len(path.parts) == 1:
        return name in SOURCE_ROOT
    if path.parts[0] not in SOURCE_DIRS:
        return False
    if path.parts[0] == 'dataset':
        return path.parent.as_posix() == 'dataset' and path.suffix == '.md'
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if (path.name in {'bge-m3-tokenizer.json', 'credentials.json', 'voices.json'}
            or path.name.startswith('service-account')
            or path.suffix.lower() in EXCLUDED_SUFFIXES):
        return False
    return not any(part in EXCLUDED_DIRS or part.startswith('.') for part in path.parts[:-1]) \
        and path.parts[:2] != ('speech', 'data')


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def verify(archive):
    with ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('MANIFEST.json'))
        names = bundle.namelist()
        expected = manifest['files']
        if len(names) != len(set(names)) or set(names) != {'MANIFEST.json', *expected}:
            raise ValueError('Archive entries differ from the manifest')
        for name, sha in expected.items():
            if not source_path(name) or checksum(bundle.read(name)) != sha:
                raise ValueError(f'Archive verification failed for {name}')
        return manifest


def build(root, destination, version):
    root, destination = root.resolve(), destination.resolve()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version):
        raise ValueError('Use a simple release version')
    checksum_path = destination.with_suffix(destination.suffix + '.sha256')
    if destination.exists() or checksum_path.exists():
        raise ValueError('Release output already exists')
    candidates = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        hashes = {}
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as bundle:
            for name in sorted(set(os.fsdecode(candidates).split('\0'))):
                if not source_path(name):
                    continue
                file = root / name
                if not file.is_file() or file.resolve() != file:
                    continue
                data = file.read_bytes()
                hashes[name] = checksum(data)
                bundle.writestr(name, data)
            if not {'README.md', 'run_eval.py'} <= hashes.keys():
                raise ValueError('Expected repository README and eval entrypoint')
            manifest = {'version': version, 'files': hashes}
            bundle.writestr('MANIFEST.json', json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        verify(temporary)
        archive_hash = checksum(temporary.read_bytes())
        os.link(temporary, destination)
        with checksum_path.open('x', encoding='utf-8') as handle:
            handle.write(f'{archive_hash}  {destination.name}\n')
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Build or verify a BTC source submission archive')
    command = parser.add_subparsers(dest='command', required=True)
    builder = command.add_parser('build')
    builder.add_argument('--root', type=Path, default=ROOT)
    builder.add_argument('--out', type=Path, required=True)
    builder.add_argument('--version', required=True)
    checker = command.add_parser('verify')
    checker.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        manifest = (build(args.root, args.out, args.version) if args.command == 'build'
                    else verify(args.archive))
    except (OSError, ValueError, KeyError, BadZipFile, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Package failed: {exc}\n')
    print(f"{manifest['version']}: {len(manifest['files'])} files verified")


if __name__ == '__main__':
    main()
