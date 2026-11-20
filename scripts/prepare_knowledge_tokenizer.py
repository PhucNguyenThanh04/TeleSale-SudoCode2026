import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'ai-services/app/mcp_servers/mcp_knowledge/assets/bge-m3-tokenizer.json'


def prepare(config_path, target, *, download=False):
    config = json.loads(Path(config_path).read_text())
    revision, expected = config['tokenizer_revision'], config['tokenizer_sha256']
    if not re.fullmatch('[0-9a-f]{40}', revision) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Pinned revision and SHA256 required')
    target = Path(target)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('Existing tokenizer checksum differs; inspect it before replacing')
        return {'status':'verified','sha256':expected}
    if not download:
        raise FileNotFoundError('Tokenizer missing; run again with --download during setup')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        url = f'https://huggingface.co/BAAI/bge-m3/resolve/{revision}/tokenizer.json'
        checksum = hashlib.sha256()
        with urlopen(url, timeout=60) as response, tempfile.NamedTemporaryFile(
                dir=target.parent, prefix='.tokenizer-', delete=False) as output:
            temporary = Path(output.name)
            while chunk := response.read(256 * 1024):
                checksum.update(chunk); output.write(chunk)
        if checksum.hexdigest() != expected:
            raise ValueError('Downloaded tokenizer checksum mismatch')
        os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'status':'downloaded','sha256':expected}


def main():
    parser = argparse.ArgumentParser(description='Verify the ignored BGE tokenizer, or explicitly download its pinned bytes.')
    parser.add_argument('--config', type=Path, default=ROOT/'config/policy-runtime.json')
    parser.add_argument('--download', action='store_true', help='Allow HTTPS download during setup only')
    args = parser.parse_args()
    try:
        result = prepare(args.config, TARGET, download=args.download)
    except Exception as exc:
        parser.exit(1, f'Tokenizer setup failed ({type(exc).__name__}): check file/config or use --download if missing.\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
