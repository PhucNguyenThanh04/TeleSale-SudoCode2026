from collections import Counter
import hashlib
import json
from pathlib import Path

from eval_harness.extractor import extract_detailed

IDENTITY = ('run_id', 'config', 'scenario_id', 'call', 'turn')
VERSION = 1
FINGERPRINT_COMPONENTS = ('extractor.py', 'extraction_report.py')


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extraction_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in FINGERPRINT_COMPONENTS:
        digest.update(name.encode() + b'\0' + Path(__file__).with_name(name).read_bytes() + b'\0')
    return digest.hexdigest()


def make_extraction_row(trace_row: dict, result: dict) -> dict:
    return {**{key: trace_row[key] for key in IDENTITY}, 'version': VERSION,
        'extractor_fingerprint': extraction_fingerprint(),
        'agent_text_sha256': hashlib.sha256(trace_row['agent_text'].encode()).hexdigest(),
        'candidates': result['candidates']}


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def write_extraction_sidecar(trace: Path, output: Path) -> None:
    if output.exists():
        raise ValueError('Refusing existing extraction sidecar')
    from eval_harness.official_pipeline import atomic_bytes
    rows = [make_extraction_row(row, extract_detailed(row['agent_text'])) for row in _rows(trace)]
    atomic_bytes(output, ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode())


def summarize_extraction(traces: dict[str, Path], sidecars: dict[str, Path], btc_score: dict) -> dict:
    if set(traces) != {'full', 'baseline_no_memory'} or set(sidecars) != set(traces):
        raise ValueError('Extraction requires both configurations')
    fingerprint = extraction_fingerprint()
    configs, bindings = {}, {}
    review = False
    for config, trace in traces.items():
        trace, sidecar = Path(trace), Path(sidecars[config])
        before = (sha256(trace), sha256(sidecar))
        rows, details = _rows(trace), _rows(sidecar)
        if len(rows) != len(details) or not rows:
            raise ValueError('Extraction coverage mismatch')
        seen = set()
        all_candidates = []
        for row, detail in zip(rows, details):
            identity = tuple(row[k] for k in IDENTITY)
            if identity in seen or row['config'] != config or any(detail.get(k) != row[k] for k in IDENTITY):
                raise ValueError('Extraction identity/order mismatch')
            seen.add(identity)
            expected = make_extraction_row(row, extract_detailed(row['agent_text']))
            if detail != expected or detail['extractor_fingerprint'] != fingerprint:
                raise ValueError('Extraction fingerprint/text/candidate mismatch')
            candidates = detail['candidates']
            ids = [c['candidate_id'] for c in candidates]
            if len(set(ids)) != len(ids):
                raise ValueError('Duplicate candidate')
            for kind, field in (('question', 'questions'), ('claim', 'claims')):
                projections = [c['projection'] for c in candidates if c['kind'] == kind and c['disposition'] == 'emitted']
                if projections != row[field]:
                    raise ValueError('Extraction projection mismatch')
            all_candidates.extend(candidates)
        summary = {}
        for kind in ('question', 'claim'):
            candidates = [c for c in all_candidates if c['kind'] == kind]
            counts = Counter(c['disposition'] for c in candidates)
            if set(counts) - {'emitted', 'excluded', 'unresolved'}:
                raise ValueError('Invalid disposition')
            uncertain = sum(bool(c['uncertainty']) for c in candidates if c['disposition'] == 'emitted')
            summary[kind] = {'detected': len(candidates), **{k: counts[k] for k in ('emitted', 'unresolved', 'excluded')},
                'emitted_uncertain': uncertain, 'reasons': dict(Counter(c['reason'] for c in candidates)),
                'emission_rate': counts['emitted'] / len(candidates) if candidates else None}
            review |= bool(counts['unresolved'] or uncertain or any(c['kind'] == 'claim' and c['reason'] in
                {'unsupported_mapping', 'qualified_not_representable'} for c in candidates))
        summary['btc_checked'] = btc_score.get('system' if config == 'full' else 'baseline', {})
        configs[config] = summary
        if before != (sha256(trace), sha256(sidecar)):
            raise ValueError('Extraction inputs changed')
        bindings[config] = {'trace': str(trace.resolve()), 'sidecar': str(sidecar.resolve()),
            'trace_sha256': before[0], 'sidecar_sha256': before[1]}
    return {'version': VERSION, 'extractor_fingerprint': fingerprint,
        'fingerprint_components': list(FINGERPRINT_COMPONENTS), 'artifacts': bindings, 'configs': configs,
        'extraction_status': 'needs_review' if review else 'complete',
        'limitations': 'Candidate counters are not detection recall; complete is not proof of perfect extraction.'}


def verify_extraction_report(report_path: Path) -> dict:
    report = json.loads(Path(report_path).read_text())
    try:
        bindings = report['artifacts']
        traces = {k: Path(v['trace']) for k, v in bindings.items()}
        sidecars = {k: Path(v['sidecar']) for k, v in bindings.items()}
        score = {('system' if k == 'full' else 'baseline'): v['btc_checked'] for k, v in report['configs'].items()}
        expected = summarize_extraction(traces, sidecars, score)
        if expected != report:
            raise ValueError('Extraction summary/hash mismatch')
    except (KeyError, OSError, TypeError) as exc:
        raise ValueError('Invalid extraction report') from exc
    return report
