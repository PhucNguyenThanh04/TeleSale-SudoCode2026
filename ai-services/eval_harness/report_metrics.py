"""Display saved BTC scores without models, DB access, rescoring or mutation."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path


MISSING = 'Chưa đo'


def _value(metrics, path):
    value = metrics
    for key in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _rate(metrics, name, numerator=None, denominator=None):
    metric = metrics.get(name) or {}
    value = metric.get('value')
    if value is None:
        return MISSING
    result = f'{value}%'
    if numerator in metric and denominator in metric:
        result += f' ({metric[numerator]}/{metric[denominator]})'
    return result


def _claim_mismatch_notes(directory, run, score):
    from eval_harness.claim_evidence import explain_claim_mismatch
    snapshots = directory / 'scenarios'
    if not snapshots.is_dir():
        return []
    specs, dates = {}, {}
    for path in sorted(snapshots.glob('*.json')):
        scenario = json.loads(path.read_text())
        on = date(2026, 10, 15)
        for call, spec in scenario['calls'].items():
            on = date.fromisoformat(spec['call_date']) if 'call_date' in spec else on + timedelta(days=spec.get('days_later', 0))
            key = (scenario['scenario_id'], call)
            specs[key], dates[key] = spec, on.isoformat()
    notes = []
    for config, key, label in [('full', 'system', 'Full'), ('baseline_no_memory', 'baseline', 'Baseline')]:
        trace = (run.get('traces') or {}).get(config)
        if not trace or not (directory / trace).is_file():
            continue
        rows = [json.loads(line) for line in (directory / trace).read_text().splitlines()]
        by_turn = {(r['scenario_id'], r['call'], r['turn']): r for r in rows}
        for example in score.get(key, {}).get('hallucination_rate', {}).get('examples', []):
            identity = (example['scenario'], example['call'])
            row = by_turn.get((*identity, example['turn']))
            explanation = (explain_claim_mismatch(row, example['field'], example['claimed'], on=dates[identity])
                           if row is not None and identity in dates else {'status': 'unresolved'})
            message = 'chưa đủ bằng chứng quote tương thích để phân loại nguyên nhân.'
            if explanation['status'] == 'supported_by_quote':
                message = f"khớp quote {explanation['sku']}; lệch ground truth."
                expected = ((specs[identity].get('success_if') or {}).get('args_match') or {}).get('sku')
                if example['field'] == 'price_vnd' and expected and expected != explanation['sku']:
                    message += f' Giá thuộc sản phẩm khác SKU kỳ vọng {expected}; vẫn giữ lỗi chọn sản phẩm.'
            notes.append(f"- {label} {identity[0]}/{identity[1]}/turn {example['turn']}, {example['field']}: {message}")
    return notes


def render_run(directory: Path) -> str:
    run = json.loads((directory / 'run.json').read_text())
    if run.get('status') != 'validated':
        raise ValueError('Chỉ hiển thị bảng điểm cho run validated; run này chưa hoàn tất.')
    score_path = directory / 'btc_score.json'
    if run.get('score') != score_path.name:
        raise ValueError('Không tìm thấy tham chiếu btc_score.json hợp lệ.')
    score = json.loads(score_path.read_text())
    full, baseline = score['system'], score['baseline']
    coverage = run.get('coverage') or {}
    lines = [f"Run: {run.get('run_id', directory.name)} (số liệu đã lưu)",
             f"Execution: {run.get('execution_health', 'unknown')}; extraction: {run.get('extraction_status', 'unknown')}",
             f"Phạm vi mỗi cấu hình: {coverage.get('scenarios', '?')} kịch bản, "
             f"{coverage.get('calls', '?')} cuộc, {coverage.get('turns', '?')} lượt.",
             '', '| Chỉ số | Full | Baseline không memory |', '|---|---:|---:|']
    rates = [('RQR ↓', 'repeat_question_rate', 'redundant', 'total_questions'),
             ('CCR ↑', 'context_carryover_rate', 'used', 'required'),
             ('TSR ↑', 'task_success_rate', 'passed', 'total'),
             ('HR ↓', 'hallucination_rate', 'wrong', 'total_claims')]
    for label, name, num, den in rates:
        lines.append(f'| {label} | {_rate(full, name, num, den)} | {_rate(baseline, name, num, den)} |')
    for label, parent, key in [('TSR ca khó ↑', 'task_success_rate', 'hard_cases'),
                              ('HR giá/KM ↓', 'hallucination_rate', 'price_promo_only')]:
        cells = [_rate({key: m.get(parent, {}).get(key)}, key, 'wrong', 'total') for m in (full, baseline)]
        lines.append(f'| {label} | {cells[0]} | {cells[1]} |')
    fields = [('Số lượt TB/cuộc', 'avg_turns_per_call'),
              ('Calls-to-close', 'calls_to_close.value'),
              ('Guardrail violations', 'guardrail_violations.total')]
    for field, title in [('ttft', 'TTFT'), ('total', 'Total'), ('call_brief', 'Call Brief')]:
        fields += [(f'{title} {pct} (ms)', f'latency.{field}.{pct}_ms') for pct in ('p50', 'p95')]
    for label, path in fields:
        cells = [_value(m, path) for m in (full, baseline)]
        cells = [MISSING if v is None else str(v) for v in cells]
        lines.append(f'| {label} | {cells[0]} | {cells[1]} |')
    lines.append(f'| WER/CER, entity accuracy ASR | {MISSING} trong eval text | {MISSING} trong eval text |')
    lines.append('')
    for label, key in [('RQR giảm ≥40%', 'meets_rqr_threshold_40pct'),
                       ('TSR ≥70%', 'meets_tsr_70pct'), ('HR giá/KM ≤5%', 'meets_hr_price_5pct')]:
        value = score.get('comparison', {}).get(key)
        status = 'ĐẠT' if value is True else 'CHƯA ĐẠT' if value is False else MISSING
        lines.append(f'{label}: {status}')
    if not run.get('latency_scale_sufficient'):
        lines.append('Chưa đủ ≥100 lượt/cấu hình để đánh giá p95 theo hướng dẫn BTC.')
    if run.get('extraction_status') != 'complete':
        lines.append('Extractor còn cần rà soát; không coi claim chưa phân giải là đúng.')
    lines.append('CCR không phải tỷ lệ fact đã lưu/đọc thành công; thiếu ghi nhận sử dụng không tự chứng minh memory quên.')
    lines.append('HR BTC đối chiếu ground_truth_facts; một sai lệch không tự chứng minh agent bịa thông tin.')
    notes = _claim_mismatch_notes(directory, run, score)
    if notes:
        lines.extend(['', 'Đối chiếu quote cho các ví dụ HR được lưu (không điều chỉnh điểm BTC):', '', *notes, ''])
    lines.append('Bảng đọc nguyên số từ btc_score.json; không phải một lần eval mới.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='Thư mục run hoặc file run.json')
    args = parser.parse_args()
    directory = args.run.parent if args.run.is_file() else args.run
    try:
        print(render_run(directory))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
