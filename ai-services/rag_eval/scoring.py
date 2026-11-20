import math
import re
import statistics
import unicodedata
from pathlib import Path

from rag_eval.dataset import load_cases, load_module, read_json, write_json
from rag_eval.runner import read_trace, seal, separate_output, sha256, verify_run


def validated_run(run):
    run = Path(run)
    manifest = verify_run(run)
    if manifest.get('kind') != 'collection' or manifest.get('status') != 'complete':
        raise ValueError('Collection incomplete; inspect trace before starting a new run')
    cases = load_cases(run / 'btc', run / 'contexts.json')
    rows = read_trace(run)
    expected = {c['qid']: c for c in cases}
    if len(rows) != len(cases) or {r.get('qid') for r in rows} != set(expected):
        raise ValueError('Exact QA coverage required: missing, duplicate or unknown qid')
    for row in rows:
        if row.get('input') != expected[row['qid']]['input']:
            raise ValueError('Trace input does not match frozen case')
        if row.get('status') not in {'ok', 'failed'} or row.get('top_k') != manifest['top_k']:
            raise ValueError('Invalid trace status or budget')
        result = row.get('retrieval')
        if result:
            if result.get('context', {}).get('knowledge_release_id') != manifest['release']['release_id']:
                raise ValueError('Trace release mismatch')
            evidence = result.get('evidence', [])
            if (not isinstance(evidence, list) or any(not isinstance(e, dict)
                    or not isinstance(e.get('chunk_id'), str) or not e['chunk_id']
                    or not isinstance(e.get('content'), str) for e in evidence)
                    or len({e['chunk_id'] for e in evidence}) != len(evidence)):
                raise ValueError('Invalid ordered evidence')
        if row.get('status') == 'ok' and (not result or result.get('retrieval_status') not in {'ok', 'no_evidence'}):
            raise ValueError('Successful trace lacks retrieval result')
        if manifest['mode'] == 'end-to-end' and row['status'] == 'ok':
            if not isinstance(row.get('answer'), str) or not row['answer'].strip() or row.get('action') not in {'answer', 'clarify', 'refuse', 'handoff'}:
                raise ValueError('Successful trace lacks valid generated answer')
    return manifest, cases, rows


def literal_checks(answer, rules):
    text = unicodedata.normalize('NFC', answer)
    missing = [p for p in rules.get('must_all', []) if not re.search(p, text, re.I)]
    forbidden = [p for p in rules.get('must_not', []) if re.search(p, text, re.I)]
    return {'passed': not missing and not forbidden, 'missing_patterns': missing,
            'forbidden_patterns': forbidden, 'semantic_correctness_evaluated': False}


def metric(values, eligible):
    values = [float(v) for v in values if v is not None]
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError('Invalid metric value')
    return {'value': statistics.mean(values) if values else None,
            'measured': len(values), 'eligible': eligible}


def latency(rows, field):
    values = sorted(r[field] for r in rows if field in r)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Invalid latency')
    return {'measured': len(values), 'p50_ms': statistics.median(values) if values else None,
            'p95_ms': values[math.ceil(.95 * len(values)) - 1] if values else None}


def calibration(labels, judgments, trace_hash):
    if labels.get('trace_sha256') != trace_hash:
        raise ValueError('Human labels belong to a different trace')
    if not isinstance(labels.get('reviewer'), str) or not labels['reviewer'].strip():
        raise ValueError('Human reviewer required')
    if set(labels.get('cases', {})) - judgments.keys():
        raise ValueError('Unknown human-label qid')
    pairs = []
    for qid, label in labels.get('cases', {}).items():
        human = label.get('correct')
        judged = (judgments[qid].get('business') or {}).get('correct')
        if human is not None and type(human) is not bool:
            raise ValueError('Human correctness must be boolean or null')
        if type(human) is bool and type(judged) is bool:
            pairs.append((human, judged))
    n = len(pairs)
    agreement = sum(a == b for a, b in pairs) / n if n else None
    if n:
        human_yes = sum(a for a, _ in pairs) / n
        judge_yes = sum(b for _, b in pairs) / n
        chance = human_yes * judge_yes + (1 - human_yes) * (1 - judge_yes)
        kappa = (agreement - chance) / (1 - chance) if chance < 1 else None
    else:
        kappa = None
    return {'samples': n, 'agreement': agreement, 'cohens_kappa': kappa,
            'sufficient_samples': n >= 20, 'reviewer': labels['reviewer']}


def score_run(run, out, *, judgments=None, judge_identity=None, human_labels=None):
    run, out = Path(run), Path(out)
    separate_output(out, run)
    manifest, cases, rows = validated_run(run)
    by_id = {r['qid']: r for r in rows}
    judgments = judgments or {}
    if judgments and set(judgments) != set(by_id):
        raise ValueError('Exact judgment coverage required')
    rules = read_json(run / 'assertions.json')
    if rules.get('schema_version') != 1 or set(rules['cases']) - by_id.keys():
        raise ValueError('Invalid assertion fixture')
    exported, details = {}, []
    for case in cases:
        qid, labels = case['qid'], case['labels']
        row = by_id[qid]
        result = row.get('retrieval') or {}
        successful_retrieval = result.get('retrieval_status') in {'ok', 'no_evidence'} and not result.get('error')
        ids = [e['chunk_id'] for e in result.get('evidence', [])] if successful_retrieval else []
        relevant = set(labels['relevant_chunk_ids'])
        normalized = [key.split('#')[0] for key in ids]
        business = judgments.get(qid, {}).get('business') or {}
        action = business.get('action') if judgments else row.get('action')
        exported[qid] = {'retrieved_chunk_ids': ids, 'abstained': action in {'refuse', 'handoff'},
                         'answer': row.get('answer') or ''}
        detail = {'qid': qid, 'type': labels['type'], 'execution_status': row['status'],
            'retrieval_status': result.get('retrieval_status', 'failed'), 'retrieved_chunk_ids': ids,
            'expected_chunk_ids': sorted(relevant),
            'hit@3': bool(relevant & set(normalized[:3])) if relevant else None,
            'hit@5': bool(relevant & set(normalized[:5])) if relevant else None,
            'full@3': relevant <= set(normalized[:3]) if relevant else None,
            'full@5': relevant <= set(normalized[:5]) if relevant else None,
            'mrr@5': next((1 / (i + 1) for i, key in enumerate(normalized[:5]) if key in relevant), 0) if relevant else None,
            'judgment': judgments.get(qid)}
        if qid in rules['cases'] and row.get('answer'):
            detail['literal_diagnostics'] = literal_checks(row['answer'], rules['cases'][qid])
        details.append(detail)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'rag_results.json', exported)
    raw_btc = load_module(run / 'btc/eval/reference_eval.py').rag_eval(
        run / 'btc/rag/qa_labeled.json', out / 'rag_results.json')
    btc = dict(raw_btc)
    if manifest['mode'] == 'retrieval':
        for key in list(btc):
            if 'abstain' in key:
                btc[key] = None
        abstention_source = 'unmeasured'
    else:
        abstention_source = 'business_judge' if judgments else 'generator_self_report'
        incomplete_generation = any(r['status'] != 'ok' for r in rows)
        incomplete_judge = judgments and any(not j.get('business') for j in judgments.values())
        if incomplete_judge or (not judgments and incomplete_generation):
            for key in list(btc):
                if 'abstain' in key:
                    btc[key] = None
            abstention_source = 'incomplete_judge_unmeasured' if judgments else 'incomplete_generation_unmeasured'
    n = len(cases)
    type_for = {c['qid']: c['labels']['type'] for c in cases}
    def business_metric(field, types=None):
        selected = [qid for qid in by_id if types is None or type_for[qid] in types]
        return metric([(judgments.get(qid, {}).get('business') or {}).get(field) for qid in selected], len(selected))
    report = {'schema_version': 1, 'provenance': {k: manifest[k] for k in
        ('dataset_hash', 'mode', 'generator', 'retriever', 'release', 'top_k', 'implementation')},
        'trace_sha256': sha256(run / 'trace.jsonl'), 'judge': judge_identity,
        'coverage': {'expected': n, 'recorded': len(rows),
            'execution_failed': sum(r['status'] != 'ok' for r in rows),
            'judge_business_failed_or_skipped': n - sum(bool(j.get('business')) for j in judgments.values()) if judgments else None},
        'btc': btc, 'btc_abstention_source': abstention_source,
        'retrieval': {'recall_denominator': sum(bool(c['labels']['relevant_chunk_ids']) for c in cases),
            'mrr@5': metric([d['mrr@5'] for d in details], sum(bool(c['labels']['relevant_chunk_ids']) for c in cases)),
            'latency': latency(rows, 'retrieval_ms')},
        'generation_latency': latency(rows, 'generation_ms'),
        'answers': {'correctness': business_metric('correct'),
            'version_accuracy': business_metric('version_correct', {'version_conflict'}),
            'numeric_accuracy': business_metric('numeric_correct', {'numeric'}),
            'restricted_leakage': business_metric('restricted_leak', {'restricted'}),
            'faithfulness': metric([j.get('faithfulness') for j in judgments.values()],
                sum((j.get('business') or {}).get('action') == 'answer' for j in judgments.values())),
            'factual_correctness_f1': metric([j.get('factual_correctness') for j in judgments.values()], n)},
        'by_type': {t: {'n': sum(d['type'] == t for d in details),
                       'hit@5': metric([d['hit@5'] for d in details if d['type'] == t],
                                      sum(d['type'] == t and d['hit@5'] is not None for d in details))}
                    for t in sorted(set(type_for.values()))},
        'cases': details,
        'limitations': ['BTC recall is query-level any-hit, not fraction of gold chunks.',
            'Abstention derived from action; generator action is self-reported until judged.',
            'Literal checks are diagnostics; no human calibration is implied.',
            'Component date/tool fixtures do not measure agent verification or tool routing.',
            'Run collection can complete with failed cases; inspect coverage.']}
    if human_labels:
        report['calibration'] = calibration(read_json(human_labels), judgments, report['trace_sha256'])
    write_json(out / 'report.json', report)
    write_json(out / 'human_labels.template.json', {'trace_sha256': report['trace_sha256'],
        'reviewer': '', 'cases': {c['qid']: {'correct': None, 'note': ''} for c in cases}})
    write_json(out / 'judgments.json', judgments)
    lines = ['# RAG evaluation', '', f"Mode: {manifest['mode']}; recorded {len(rows)}/{n}; failed {report['coverage']['execution_failed']}.",
             f"Release: {manifest['release']['release_id']}. Abstention: {abstention_source}.",
             '', '| Metric | Value |', '|---|---:|']
    for key, value in btc.items():
        if isinstance(value, (int, float)) or value is None:
            lines.append(f'| BTC {key} | {value} |')
    for key, value in report['answers'].items():
        lines.append(f"| {key} | {value['value']} ({value['measured']}/{value['eligible']} measured) |")
    lines += ['', '## Per-question diagnostics', '', '| QID | Type | Execution | Hit@3 | Hit@5 | Full@5 |', '|---|---|---|---|---|---|']
    lines += [f"| {d['qid']} | {d['type']} | {d['execution_status']} | {d['hit@3']} | {d['hit@5']} | {d['full@5']} |" for d in details]
    lines += ['', *['- ' + note for note in report['limitations']]]
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    seal(out, {'schema_version': 1, 'kind': 'scores', 'status': 'complete',
               'source_manifest_sha256': sha256(run / 'manifest.json'),
               'source_trace_sha256': report['trace_sha256']})
    return report


def compare(before, after):
    for path in (before, after):
        if verify_run(path).get('kind') != 'scores':
            raise ValueError('Comparison requires scored artifacts')
    a, b = (read_json(Path(path) / 'report.json') for path in (before, after))
    for key in ('dataset_hash', 'mode', 'generator'):
        if a['provenance'][key] != b['provenance'][key]:
            raise ValueError('Incompatible comparison: ' + key)
    if a['judge'] != b['judge']:
        raise ValueError('Incompatible comparison: judge')
    a_rows = {row['qid']: row for row in a['cases']}
    b_rows = {row['qid']: row for row in b['cases']}
    if a_rows.keys() != b_rows.keys():
        raise ValueError('Incompatible comparison coverage')
    def correct(row):
        return ((row.get('judgment') or {}).get('business') or {}).get('correct')
    return {'before_release': a['provenance']['release'], 'after_release': b['provenance']['release'],
        'source_reports': {'before_sha256': sha256(Path(before) / 'report.json'),
                           'after_sha256': sha256(Path(after) / 'report.json')},
        'before_top_k': a['provenance']['top_k'], 'after_top_k': b['provenance']['top_k'],
        'before_retriever': a['provenance']['retriever'], 'after_retriever': b['provenance']['retriever'],
        'retrieval_delta': {key: b['btc'][key] - a['btc'][key] for key in
            ('recall@3', 'recall@5', 'multi_hop_full_recall@3', 'multi_hop_full_recall@5')
            if a['btc'][key] is not None and b['btc'][key] is not None},
        'answer_delta': {key: b['answers'][key]['value'] - a['answers'][key]['value']
            if a['answers'][key]['value'] is not None and b['answers'][key]['value'] is not None else None
            for key in a['answers']},
        'answer_coverage': {'before': a['answers'], 'after': b['answers']},
        'retrieval_improved': [qid for qid in a_rows if a_rows[qid]['hit@5'] is False and b_rows[qid]['hit@5'] is True],
        'retrieval_regressed': [qid for qid in a_rows if a_rows[qid]['hit@5'] is True and b_rows[qid]['hit@5'] is False],
        'answer_improved': [qid for qid in a_rows if correct(a_rows[qid]) is False and correct(b_rows[qid]) is True],
        'answer_regressed': [qid for qid in a_rows if correct(a_rows[qid]) is True and correct(b_rows[qid]) is False],
        'coverage': {'before': a['coverage'], 'after': b['coverage']},
        'note': 'Retrieval deltas are percentage points; answer deltas use 0–1. Compare measured coverage before interpreting deltas. No statistical significance is claimed.'}
