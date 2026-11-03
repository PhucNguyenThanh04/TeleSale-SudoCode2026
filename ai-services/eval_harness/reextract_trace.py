"""Re-extract speech annotations offline; this is never a new agent evaluation."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from eval_harness.extractor import extract_claims, extract_questions


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
        updated['questions'] = extract_questions(row['agent_text'])
        updated['claims'] = extract_claims(row['agent_text'], row['tool_calls'])
        result.append(updated)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenarios', type=Path)
    parser.add_argument('--btc-root', type=Path)
    parser.add_argument('--config', choices=['full', 'baseline_no_memory'])
    args = parser.parse_args()
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
        os.link(temporary, args.output)  # Exclusive publication, never overwrites.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'kind':'offline-extraction-only', 'rows':len(updated),
                      'input_sha256':hashlib.sha256(raw).hexdigest(),
                      'exact_coverage_audited':all(bool(o) for o in audit_options),
                      'facts_used':'preserved; prior snapshot unavailable in public trace'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
