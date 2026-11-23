import hashlib
import json
from pathlib import Path
import shutil


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root):
    return {str(path.relative_to(root)): _hash(path) for path in sorted(root.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts and path.name != 'btc_release.json'}


def release_metadata(root: Path) -> dict:
    root = Path(root)
    marker = root / 'btc_release.json'
    if marker.is_file():
        return {'version': json.loads(marker.read_text())['version'], 'snapshot_sha256': _hash(marker)}
    return {'version': 'explicit_btc_root', 'scorer_sha256': _hash(root / 'eval/reference_eval.py')}


def prepare_btc_release(base: Path, destination: Path) -> Path:
    base, destination = Path(base).resolve(), Path(destination).resolve()
    marker = base / 'btc_release.json'
    if marker.is_file():
        if json.loads(marker.read_text()).get('effective_files') != _files(base):
            raise ValueError('btc_release_changed')
        return base
    for relative in ('eval/reference_eval.py', 'eval/mock_tools.py', 'schemas/tools.schema.json',
                     'catalog/products.json', 'schemas/trace_log.schema.json', 'schemas/scenario_format.md'):
        if not (base / relative).is_file():
            raise ValueError('btc_base_missing:' + relative)
    if destination.exists():
        raise FileExistsError('btc_release_exists_choose_new_path')
    if destination == base or base in destination.parents:
        raise ValueError('btc_release_destination_inside_source')
    source_files = {}
    destination.mkdir(parents=True)
    try:
        for folder in ('catalog', 'policy', 'schemas', 'rag', 'simulator'):
            if (base / folder).is_dir():
                shutil.copytree(base / folder, destination / folder)
        (destination / 'eval').mkdir()
        for path in sorted((base / 'eval').glob('*.py')):
            shutil.copy2(path, destination / 'eval' / path.name)
        rubric = base / 'eval/llm_judge_rubric.json'
        if rubric.is_file():
            shutil.copy2(rubric, destination / 'eval' / rubric.name)
        for path in sorted(base.glob('*.md')):
            shutil.copy2(path, destination / path.name)
        source_files = _files(destination)
        provenance = {'version': 'explicit_btc_root', 'base': str(base),
                      'base_files': source_files, 'effective_files': _files(destination)}
        (destination / 'btc_release.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    except Exception:
        shutil.rmtree(destination)
        raise
    return destination
