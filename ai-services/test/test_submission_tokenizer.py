import hashlib
import importlib.util
import io
import json
from pathlib import Path
import pytest


def module():
    path = Path(__file__).resolve().parents[2] / 'scripts/prepare_knowledge_tokenizer.py'
    spec = importlib.util.spec_from_file_location('submission_tokenizer', path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def inputs(tmp_path):
    content = b'{"version":"1.0","model":{}}'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'tokenizer_revision':'a'*40,
        'tokenizer_sha256':hashlib.sha256(content).hexdigest()}))
    return config, tmp_path/'assets'/'tokenizer.json', content


def test_default_checks_without_downloading_and_accepts_verified_existing(tmp_path, monkeypatch):
    m = module(); config, target, content = inputs(tmp_path)
    monkeypatch.setattr(m, 'urlopen', lambda *a, **k: pytest.fail('No implicit download'))
    with pytest.raises(FileNotFoundError): m.prepare(config, target)
    target.parent.mkdir(); target.write_bytes(content)
    assert m.prepare(config, target)['status'] == 'verified'


def test_download_is_pinned_and_bad_hash_never_publishes(tmp_path, monkeypatch):
    m = module(); config, target, content = inputs(tmp_path); urls = []
    def download(url, **kwargs):
        urls.append(url); return io.BytesIO(content)
    monkeypatch.setattr(m, 'urlopen', download)
    assert m.prepare(config, target, download=True)['status'] == 'downloaded'
    assert '/resolve/'+'a'*40+'/tokenizer.json' in urls[0]
    target.unlink()
    monkeypatch.setattr(m, 'urlopen', lambda *a, **k: io.BytesIO(b'wrong'))
    with pytest.raises(ValueError, match='checksum'): m.prepare(config, target, download=True)
    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_existing_wrong_artifact_is_not_overwritten(tmp_path, monkeypatch):
    m = module(); config, target, _ = inputs(tmp_path)
    target.parent.mkdir(); target.write_bytes(b'existing')
    monkeypatch.setattr(m, 'urlopen', lambda *a, **k: pytest.fail('Must not overwrite'))
    with pytest.raises(ValueError, match='checksum'): m.prepare(config, target, download=True)
    assert target.read_bytes() == b'existing'
