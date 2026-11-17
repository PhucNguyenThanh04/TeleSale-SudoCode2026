"""Offline candidate review with exact trace bindings; never changes BTC scores.

Evidence hashes verify the cited source, not the reviewer's semantic judgment.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from eval_harness.extraction_report import IDENTITY, sha256, verify_extraction_report


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _identity(row):
    return tuple(row[key] for key in IDENTITY)


def _inputs(report_path):
    report = verify_extraction_report(Path(report_path))
    rows, candidates, positions = {}, {}, {}
    for config, binding in report['artifacts'].items():
        traces = [json.loads(line) for line in Path(binding['trace']).read_text().splitlines()]
        details = [json.loads(line) for line in Path(binding['sidecar']).read_text().splitlines()]
        for position, (row, detail) in enumerate(zip(traces, details)):
            key = _identity(row)
            rows[key], positions[key] = row, position
            for candidate in detail['candidates']:
                if (candidate['disposition'] == 'unresolved'
                        or candidate['disposition'] == 'emitted' and candidate['uncertainty']
                        or candidate['kind'] == 'claim' and candidate['reason'] in {
                            'unsupported_mapping', 'qualified_not_representable'}):
                    item = {**{k: row[k] for k in IDENTITY}, 'candidate_id': candidate['candidate_id'],
                        'candidate_sha256': _digest(candidate), 'kind': candidate['kind'],
                        'text': candidate['text'], 'reason': candidate['reason'],
                        'qualifiers': candidate['qualifiers']}
                    candidates[(*key, candidate['candidate_id'])] = item
    return rows, candidates, positions


def review_template(report_path):
    _, candidates, _ = _inputs(report_path)
    return {'version': 1, 'extraction_report_sha256': sha256(Path(report_path)),
        'reviewer': {'name': '', 'kind': 'human'},
        'candidates': [{**item, 'decision': 'pending', 'note': '', 'evidence': []}
                       for item in candidates.values()]}


def _source(rows, identity, pointer):
    if not (pointer == '/user_text'
            or re.fullmatch(r'/tool_calls/\d+/(?:args|result)(?:/[^/]+)*', pointer)):
        raise ValueError('Review evidence must cite customer speech or tool evidence')
    value = rows[identity]
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def evidence_reference(report_path, row, pointer):
    rows, _, _ = _inputs(report_path)
    return {**{key: row[key] for key in IDENTITY}, 'pointer': pointer,
            'sha256': _digest(_source(rows, _identity(row), pointer))}


def inspect_review(report_path, review):
    rows, expected, positions = _inputs(report_path)
    if (review.get('version') != 1
            or review.get('extraction_report_sha256') != sha256(Path(report_path))):
        raise ValueError('Review report binding mismatch')
    reviewer = review.get('reviewer', {})
    if (reviewer.get('kind') not in {'human', 'assistant'}
            or not isinstance(reviewer.get('name'), str) or not reviewer['name'].strip()):
        raise ValueError('Review authorship is required')
    seen, decisions = set(), Counter()
    for item in review['candidates']:
        identity = _identity(item)
        key = (*identity, item['candidate_id'])
        if key in seen or key not in expected or any(item.get(k) != v for k, v in expected[key].items()):
            raise ValueError('Review candidate mismatch or duplicate')
        seen.add(key)
        decision = item['decision']
        if decision not in {'pending', 'supported', 'not_assertion', 'contradicted', 'unverifiable'}:
            raise ValueError('Invalid review decision')
        if decision != 'pending' and (not isinstance(item.get('note'), str) or not item['note'].strip()):
            raise ValueError('Review judgment requires an explanation')
        if decision == 'not_assertion' and (item['kind'] != 'claim' or item['reason'] != 'unresolved_claim'):
            raise ValueError('Known factual mappings cannot be discarded as headings')
        if decision == 'supported' and not item.get('evidence'):
            raise ValueError('Supported judgment requires source evidence')
        for reference in item.get('evidence', []):
            source_id = _identity(reference)
            if (source_id not in rows or source_id[:3] != identity[:3]
                    or positions[source_id] > positions[identity]
                    or _digest(_source(rows, source_id, reference['pointer'])) != reference['sha256']):
                raise ValueError('Review source binding mismatch')
        decisions[decision] += 1
    if seen != set(expected):
        raise ValueError('Review must cover every required candidate in both configurations')
    return {'complete': not any(decisions[k] for k in ('pending', 'contradicted', 'unverifiable')),
        'reviewer': reviewer, 'reviewed': sum(decisions.values()) - decisions['pending'],
        'decisions': dict(decisions), 'extraction_report_sha256': sha256(Path(report_path)),
        'limitations': ['Review judgments are attributed to the named reviewer, not mechanically proven by hashes.',
            'Unprojected claims remain outside BTC score denominators; review does not establish extraction recall.',
            'Assistant review is not independent human review or a new agent evaluation.']}


def verify_review(report_path, review_path):
    try:
        return inspect_review(report_path, json.loads(Path(review_path).read_text()))
    except (OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError('Invalid extraction review evidence') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('template', 'check'))
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--review', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.kind == 'template':
            template = review_template(args.report)
            with args.review.open('x') as stream:
                json.dump(template, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            print(json.dumps({'status': 'pending', 'candidates': len(template['candidates'])}))
        else:
            result = verify_review(args.report, args.review)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not result['complete']:
                raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
