"""Durable independent collection; injected adapters keep offline tests offline."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rag_eval.dataset import (DEFAULT_ASSERTIONS, DEFAULT_CONTEXTS, freeze_inputs,
                              load_cases, read_json, reference_observations, write_json)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def file_hashes(root):
    return {str(p.relative_to(root)): sha256(p) for p in sorted(Path(root).rglob('*'))
            if p.is_file() and p != Path(root) / 'manifest.json' and '__pycache__' not in p.parts}


def separate_output(out, *sources):
    if any(Path(out).resolve().is_relative_to(Path(source).resolve()) for source in sources):
        raise ValueError('Output must be outside source artifact directories')


def seal(out, manifest):
    manifest['files'] = file_hashes(out)
    write_json(Path(out) / 'manifest.json', manifest)


def verify_run(out):
    manifest = read_json(Path(out) / 'manifest.json')
    if manifest.get('schema_version') != 1 or manifest.get('files') != file_hashes(out):
        raise ValueError('Artifact hash mismatch or unsupported manifest')
    return manifest


def read_trace(out):
    return [json.loads(line) for line in (Path(out) / 'trace.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]


def generation_payload(inputs, result, observations):
    return {'question': inputs['query'], 'business_context': {k: inputs[k] for k in
            ('on', 'verified_order_date', 'customer_reported_order_date', 'date_source') if k in inputs},
            'retrieval_status': result['retrieval_status'],
            'policy_evidence': result.get('evidence', []),
            'evidence_set': result.get('evidence_set', {}), 'reference_tool_observations': observations}


async def collect(root, out, retriever, generator=None, *, top_k=5,
                  context_path=DEFAULT_CONTEXTS, assertions_path=DEFAULT_ASSERTIONS):
    separate_output(out, root)
    if not 5 <= top_k <= 10:
        raise ValueError('top_k must be between 5 and 10 for BTC @3/@5')
    load_cases(root, context_path)  # Validate before creating output or calling services.
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'kind': 'collection', 'status': 'interrupted',
        'started_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'end-to-end' if generator else 'retrieval', 'top_k': top_k,
        'scope': 'isolated_rag_with_reference_tool_fixtures',
        'generator': generator.identity if generator else None,
        'retriever': getattr(retriever, 'identity', {}),
        'implementation': {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))
                           if not p.name.startswith('test_')}}
    (out / 'trace.jsonl').touch()
    try:
        freeze_inputs(root, out, context_path, assertions_path)
        if generator and getattr(generator, 'prompt', None):
            (out / 'generation_prompt.txt').write_text(generator.prompt, encoding='utf-8')
        cases = load_cases(out / 'btc', out / 'contexts.json')
        manifest['dataset_hash'] = digest({k: v for k, v in file_hashes(out).items()
                                         if k.startswith('btc/') or k in {'contexts.json', 'assertions.json'}})
        manifest['release'] = await retriever.pin()
        if not all(isinstance(manifest['release'].get(k), str) and manifest['release'][k]
                   for k in ('release_id', 'manifest_hash')):
            raise ValueError('Invalid release reference')
        seal(out, manifest)
        with (out / 'trace.jsonl').open('a', encoding='utf-8') as stream:
            for case in cases:
                row = {'qid': case['qid'], 'input': case['input'], 'top_k': top_k,
                    'status': 'failed', 'retrieval': None, 'answer': None, 'action': None,
                    'reference_tool_observations': []}
                phase = 'retrieval'
                start = time.perf_counter()
                try:
                    result = await retriever.search(case['input'], manifest['release'], top_k)
                    row['retrieval_ms'] = round((time.perf_counter() - start) * 1000, 3)
                    if result.get('context', {}).get('knowledge_release_id') != manifest['release']['release_id']:
                        raise ValueError('Release mismatch')
                    row['retrieval'] = result
                    if result.get('retrieval_status') not in {'ok', 'no_evidence'} or result.get('error'):
                        raise ValueError('Retrieval unavailable')
                    if generator:
                        phase = 'reference_tools'
                        observations = reference_observations(out / 'btc', case['input'])
                        row['reference_tool_observations'] = observations
                        payload = generation_payload(case['input'], result, observations)
                        row['generation_input'] = payload
                        phase = 'generation'
                        start = time.perf_counter()
                        generated = await generator.generate(payload)
                        if (not isinstance(generated.get('answer'), str) or not generated['answer'].strip()
                                or generated.get('action') not in {'answer', 'clarify', 'refuse', 'handoff'}):
                            raise ValueError('Invalid generation')
                        row.update(generated)
                        row['generation_ms'] = round((time.perf_counter() - start) * 1000, 3)
                    row['status'] = 'ok'
                except Exception as exc:
                    # Provider exception messages may contain credentials or customer data.
                    row['error'] = phase + '_failed'
                    row['error_type'] = type(exc).__name__
                    if phase == 'retrieval':
                        row.setdefault('retrieval_ms', round((time.perf_counter() - start) * 1000, 3))
                    elif phase == 'generation':
                        row['generation_ms'] = round((time.perf_counter() - start) * 1000, 3)
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()
                print(f"{case['qid']}: {row['status']}", flush=True)
        manifest['status'] = 'complete'
    finally:
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        seal(out, manifest)
    return manifest
