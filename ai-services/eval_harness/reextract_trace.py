import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from eval_harness.extractor import extract_detailed


def reextract_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    groups = set()
    active = None
    last_turn = 0
    if not rows:
        raise ValueError('Empty trace')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('agent_text'), str) or not isinstance(row.get('tool_calls'), list):
            raise ValueError('Missing speech or tool calls')
        group = (row.get('scenario_id'), row.get('call'))
        turn = row.get('turn')
        if not all(isinstance(value, str) and value for value in group) or type(turn) is not int:
            raise ValueError('Invalid turn identity')
        identity = (*group, turn)
        if identity in seen:
            raise ValueError('Duplicate turn')
        if group != active:
            if group in groups:
                raise ValueError('Noncontiguous call')
            groups.add(group)
            active, last_turn = group, 0
        if turn != last_turn + 1:
            raise ValueError('Out-of-order or missing turn')
        seen.add(identity)
        last_turn = turn
        updated = deepcopy(row)
        annotations = extract_detailed(row['agent_text'])
        updated.update(questions=annotations['questions'], claims=annotations['claims'])
        result.append(updated)
    return result


def _file_hashes(directory: Path) -> dict:
    from eval_harness.extraction_report import sha256
    if any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('Source snapshot must not contain symlinks')
    return {str(p.relative_to(directory)): sha256(p) for p in sorted(directory.rglob('*')) if p.is_file()}


def _metric_delta(original: dict, updated: dict) -> dict:
    result = {}
    for key, value in updated.items():
        before = original.get(key)
        if isinstance(value, dict) and isinstance(before, dict):
            result[key] = _metric_delta(before, value)
        elif type(value) in (int, float) and type(before) in (int, float):
            result[key] = round(value - before, 6)
    return result


def replay_pair(source_run: Path, output_dir: Path, btc_root: Path) -> dict:
    import shutil
    from eval_harness.official_pipeline import atomic_bytes, atomic_json
    from eval_harness.extraction_report import (sha256, extraction_fingerprint,
        write_extraction_sidecar, summarize_extraction, verify_extraction_report)
    from eval.score_pair import score_pair, _scenario_sha
    from eval.trace_audit import audit_trace, audit_pair, _btc_digest

    source_run, output_dir, btc_root = map(lambda p: Path(p).resolve(), (source_run, output_dir, btc_root))
    if output_dir.exists() or source_run in output_dir.parents or output_dir in source_run.parents:
        raise ValueError('Replay output must be a new directory outside source')
    source_hashes = _file_hashes(source_run)
    run = json.loads((source_run/'run.json').read_text())
    if run.get('status') != 'validated' or run.get('safety_issues'):
        raise ValueError('Source is incomplete or safety-invalid')

    def source_file(name):
        path = (source_run/name).resolve()
        if source_run not in path.parents or not path.is_file():
            raise ValueError('Source artifact missing or outside snapshot')
        return path

    configs = ('full', 'baseline_no_memory')
    traces = {c: source_file(run['traces'][c]) for c in configs}
    manifests = {c: json.loads(source_file(run['manifests'][c]).read_text()) for c in configs}
    if audit_pair(manifests['full'], manifests['baseline_no_memory']):
        raise ValueError('Source pair provenance mismatch')
    scenarios = source_run/'scenarios'
    score_path = source_file(run['score'])
    inputs_path = score_path.with_suffix('.inputs.json')
    inputs = json.loads(inputs_path.read_text())
    scorer = btc_root/'eval/reference_eval.py'
    btc_digest, scorer_hash = _btc_digest(scenarios, btc_root), sha256(scorer)
    fingerprint = extraction_fingerprint()
    if inputs['scenario_sha256'] != _scenario_sha(scenarios) or inputs['scorer_sha256'] != scorer_hash:
        raise ValueError('Source scenario/scorer hash mismatch')
    for config, trace in traces.items():
        manifest = manifests[config]
        audit = audit_trace(scenarios, trace, config, btc_root)
        if audit['errors']:
            raise ValueError('Source trace audit failed')
        key = 'full_trace_sha256' if config == 'full' else 'baseline_trace_sha256'
        if (sha256(trace) != inputs[key] or manifest['trace_sha256'] != sha256(trace)
                or manifest['scorer_sha256'] != scorer_hash or manifest['btc_data_digest'] != btc_digest
                or manifest['score_inputs_sha256'] != sha256(inputs_path)
                or manifest['scorer_report_sha256'] != inputs['score_sha256']
                or manifest['run_id'] != audit['run_id'] or manifest['trace_rows'] != audit['rows']
                or manifest['expected_rows'] != audit['expected_rows']
                or manifest['runner_report_sha256'] != sha256(trace.with_suffix('.report.json'))):
            raise ValueError('Source manifest/input hash mismatch')
    original = json.loads(score_path.read_text())
    issues = []
    if sha256(score_path) != inputs['score_sha256']:
        issues.append({'code': 'source_score_bytes_mismatch', 'actual_sha256': sha256(score_path),
                       'recorded_sha256': inputs['score_sha256']})
    with tempfile.TemporaryDirectory(prefix='extraction-original-') as temporary:
        rescored = Path(temporary)/'original_rescore.json'
        score_pair(scenarios, traces['full'], traces['baseline_no_memory'], rescored, btc_root=btc_root)
        if json.loads(rescored.read_text()) != original:
            raise ValueError('Original score JSON differs from pinned offline rescore; delta refused')
        if sha256(rescored) != inputs['score_sha256']:
            raise ValueError('Original scorer bytes do not match recorded provenance')
        output_dir.mkdir(parents=True, exist_ok=False)
        atomic_bytes(output_dir/'original_rescore.json', rescored.read_bytes())
        atomic_bytes(output_dir/'original_rescore.inputs.json', rescored.with_suffix('.inputs.json').read_bytes())
    shutil.copytree(scenarios, output_dir/'scenarios')
    updated_traces, sidecars = {}, {}
    for config, trace in traces.items():
        destination = output_dir/f'{config}.jsonl'
        rows = reextract_rows([json.loads(line) for line in trace.read_text().splitlines()])
        atomic_bytes(destination, ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows).encode())
        if audit_trace(output_dir/'scenarios', destination, config, btc_root)['errors']:
            raise ValueError('Replay trace audit failed')
        updated_traces[config] = destination
        sidecars[config] = output_dir/('full.extraction.jsonl' if config == 'full' else 'baseline.extraction.jsonl')
        write_extraction_sidecar(destination, sidecars[config])
    score = output_dir/'btc_score.json'
    provenance = score_pair(output_dir/'scenarios', updated_traces['full'], updated_traces['baseline_no_memory'], score, btc_root=btc_root)
    updated_score = json.loads(score.read_text())
    report_path = output_dir/'extraction_report.json'
    atomic_json(report_path, summarize_extraction(updated_traces, sidecars, updated_score))
    report = verify_extraction_report(report_path)
    if (source_hashes != _file_hashes(source_run) or scorer_hash != sha256(scorer)
            or btc_digest != _btc_digest(scenarios, btc_root) or fingerprint != extraction_fingerprint()):
        raise ValueError('Source/scorer/extractor changed during replay')
    if provenance != {**provenance, 'score_sha256': sha256(score),
            'full_trace_sha256': sha256(updated_traces['full']),
            'baseline_trace_sha256': sha256(updated_traces['baseline_no_memory']),
            'scenario_sha256': _scenario_sha(output_dir/'scenarios')}:
        raise ValueError('Replay publication hash mismatch')
    manifest = {'kind': 'offline-extraction-replay', 'status': 'complete',
        'source_run': str(source_run), 'source_hashes': source_hashes,
        'source_integrity_issues': issues, 'source_preserved': True,
        'scorer_sha256': scorer_hash, 'btc_data_digest': btc_digest,
        'scenario_sha256': provenance['scenario_sha256'],
        'extractor_fingerprint': fingerprint, 'extraction_status': report['extraction_status'],
        'extraction_report': {'path': report_path.name, 'sha256': sha256(report_path)},
        'original_score': original, 'replay_score': updated_score,
        'delta': _metric_delta(original, updated_score), 'output_hashes': _file_hashes(output_dir),
        'limitations': ['Offline annotation replay; agent behavior unchanged.',
            'facts_used preserved; prior snapshot unavailable in public trace.',
            'Self-reviewed rules/labels do not establish hidden-test generalization.']}
    atomic_json(output_dir/'replay_manifest.json', manifest)
    if json.loads((output_dir/'replay_manifest.json').read_text()) != manifest:
        raise ValueError('Replay manifest publication mismatch')
    final_hashes = _file_hashes(output_dir)
    final_hashes.pop('replay_manifest.json')
    if final_hashes != manifest['output_hashes']:
        raise ValueError('Replay artifacts changed during manifest publication')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description='Re-extract speech annotations offline; this is never a new agent evaluation.')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-run', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--scenarios', type=Path)
    parser.add_argument('--btc-root', type=Path)
    parser.add_argument('--config', choices=['full', 'baseline_no_memory'])
    args = parser.parse_args()
    if args.source_run or args.output_dir:
        if not (args.source_run and args.output_dir and args.btc_root) or any((args.input, args.output, args.scenarios, args.config)):
            parser.error('Pair mode requires --source-run, --output-dir, --btc-root exclusively')
        try:
            result = replay_pair(args.source_run, args.output_dir, args.btc_root)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        print(json.dumps({key: result[key] for key in ('kind', 'status', 'extraction_status', 'source_integrity_issues')}, ensure_ascii=False))
        return
    if not args.input or not args.output:
        parser.error('Single-file mode requires --input and --output')
    audit_options = [args.scenarios, args.btc_root, args.config]
    if any(audit_options) and not all(audit_options):
        parser.error('--scenarios, --btc-root and --config must be supplied together')
    if args.output.exists() or args.output.resolve() == args.input.resolve():
        parser.error('Output must be a new file, different from input')
    raw = args.input.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        updated = reextract_rows(rows)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    if all(audit_options):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from eval.trace_audit import audit_trace
        audit = audit_trace(args.scenarios, args.input, args.config, args.btc_root)
        if audit['errors']:
            parser.error('Input audit failed: ' + str(audit['errors']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.output.parent,
                                         prefix='.reextract-', delete=False) as stream:
            temporary = Path(stream.name)
            for row in updated:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        if all(audit_options):
            audit = audit_trace(args.scenarios, temporary, args.config, args.btc_root)
            if audit['errors']:
                parser.error('Output audit failed: ' + str(audit['errors']))
        if args.input.read_bytes() != raw:
            parser.error('Input changed during extraction')
        os.link(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'kind':'offline-extraction-only', 'rows':len(updated),
                      'input_sha256':hashlib.sha256(raw).hexdigest(),
                      'exact_coverage_audited':all(bool(o) for o in audit_options),
                      'facts_used':'preserved; prior snapshot unavailable in public trace'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
