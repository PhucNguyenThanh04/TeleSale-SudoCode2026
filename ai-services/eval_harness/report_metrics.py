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
            earlier_calls = [call for prior in rows
                if (prior['scenario_id'], prior['call']) == identity and prior['turn'] < example['turn']
                for call in prior.get('tool_calls', [])]
            explanation = (explain_claim_mismatch(row, example['field'], example['claimed'],
                                                on=dates[identity], context_calls=earlier_calls)
                           if row is not None and identity in dates else {'status': 'unresolved'})
            message = 'chưa đủ bằng chứng quote tương thích để phân loại nguyên nhân.'
            if explanation['status'] == 'supported_by_quote':
                message = f"khớp quote {explanation['sku']}; lệch ground truth."
                expected = ((specs[identity].get('success_if') or {}).get('args_match') or {}).get('sku')
                expected = expected or (specs[identity].get('facts_established') or {}).get('product_advised')
                if example['field'] == 'price_vnd' and expected and expected != explanation['sku']:
                    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
                    requested = resolve_claim_skus(row.get('user_text', row.get('customer_text', '')),
                                                   [*earlier_calls, *row.get('tool_calls', [])])
                    if {expected, explanation['sku']} <= requested:
                        message += (f' Khách hỏi nhiều sản phẩm ở lượt này; SKU kỳ vọng {expected} '
                                    'thuộc tiêu chí cuối cuộc gọi. Chưa đủ căn cứ kết luận chọn sai sản phẩm.')
                    else:
                        message += f' Giá thuộc sản phẩm khác SKU kỳ vọng {expected}; cần rà soát lựa chọn ở lượt này.'
            notes.append(f"- {label} {identity[0]}/{identity[1]}/turn {example['turn']}, {example['field']}: {message}")
    return notes


def _difference(full, baseline, path, unit=''):
    values = [_value(m, path) for m in (full, baseline)]
    if not all(type(v) in (int, float) for v in values):
        return MISSING
    return f'{values[0] - values[1]:+g}{unit}'


def _asr_lines(evidence, btc_root):
    from eval_harness.asr_evidence import verify_asr_evidence
    if not verify_asr_evidence(evidence, btc_root=btc_root):
        return ['ASR: bằng chứng không khớp hoặc không còn truy cập được; không công bố số đã đính kèm.']
    lines = ['', '| Nhóm | File | WER (%) | CER (%) | Entity (%) | Tiền (%) | SĐT (%) | Đủ bằng chứng |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    ready = True
    for group in ('btc', 'team'):
        report = evidence['groups'].get(group, {}).get('report', {})
        ready &= report.get('asr_evidence_ready') is True
        values = [report.get('dialogues'), *[_value(report, 'metrics.'+key) for key in
                  ('WER', 'CER', 'entity_accuracy', 'money.value', 'phone.value')]]
        if not report.get('input_integrity'):
            values = [None] * len(values)
        cells = [MISSING if value is None else str(value) for value in values]
        lines.append(f'| ASR {group.upper() if group == "btc" else group} | ' + ' | '.join(cells)
                     + (' | ĐẠT |' if report.get('asr_evidence_ready') else ' | CHƯA ĐỦ |'))
    lines.append('Bằng chứng pipeline ASR M1: ' + ('ĐẠT' if ready else 'CHƯA ĐỦ'))
    lines.append('Điểm xếp hạng ASR do BTC đo trên audio private ngày chấm; điểm public/team chỉ chứng minh pipeline và phân tích lỗi.')
    lines.append('ASR dùng scorer BTC, báo riêng BTC/team; không lấy trung bình WER hai nhóm và không chạy lại ASR.')
    return lines


def render_run(directory: Path, *, btc_root: Path | None = None, asr_sources=None) -> str:
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
             '', '| Chỉ số | Full | Baseline không memory | Chênh lệch Full − Baseline |', '|---|---:|---:|---:|']
    rates = [('RQR ↓', 'repeat_question_rate', 'redundant', 'total_questions'),
             ('CCR ↑', 'context_carryover_rate', 'used', 'required'),
             ('TSR ↑', 'task_success_rate', 'passed', 'total'),
             ('HR ↓', 'hallucination_rate', 'wrong', 'total_claims')]
    for label, name, num, den in rates:
        lines.append(f'| {label} | {_rate(full, name, num, den)} | {_rate(baseline, name, num, den)} | '
                     f'{_difference(full, baseline, name+".value", " đpt")} |')
    for label, parent, key in [('TSR ca khó ↑', 'task_success_rate', 'hard_cases'),
                              ('HR giá/KM ↓', 'hallucination_rate', 'price_promo_only')]:
        cells = [_rate({key: m.get(parent, {}).get(key)}, key, 'wrong', 'total') for m in (full, baseline)]
        lines.append(f'| {label} | {cells[0]} | {cells[1]} | '
                     f'{_difference(full, baseline, parent+"."+key+".value", " đpt")} |')
    fields = [('Số lượt TB/cuộc', 'avg_turns_per_call'),
              ('Calls-to-close', 'calls_to_close.value'),
              ('Guardrail violations', 'guardrail_violations.total')]
    voice_measurement = run.get('conversation_measurement', {}).get('delivery_mode') == 'voice'
    proxy_ttft = voice_measurement or run.get('conversation_measurement', {}).get('ttft_is_proxy') is True
    for field, title in [('ttft', 'TTFT proxy' if proxy_ttft else 'TTFT'),
                         ('total', 'Response' if voice_measurement else 'Total'),
                         ('call_brief', 'Call Brief')]:
        fields += [(f'{title} {pct} (ms)', f'latency.{field}.{pct}_ms') for pct in ('p50', 'p95')]
    for label, path in fields:
        cells = [_value(m, path) for m in (full, baseline)]
        cells = [MISSING if v is None else str(v) for v in cells]
        lines.append(f'| {label} | {cells[0]} | {cells[1]} | {_difference(full, baseline, path)} |')
    lines.append(f'| WER/CER, entity accuracy ASR | {MISSING} trong eval text | {MISSING} trong eval text | — |')
    lines.append('')
    lines.append('Chênh lệch tỷ lệ dùng điểm phần trăm (đpt); số âm tốt hơn với RQR/HR.')
    reduction = score.get('comparison', {}).get('rqr_relative_reduction_pct')
    from eval_harness.m1_acceptance import _rqr_check
    rqr_check = _rqr_check(full, baseline, score.get('comparison', {}))
    if rqr_check['status'] == 'not_applicable':
        lines.append('RQR giảm tương đối: Không áp dụng (Full và baseline đều RQR=0).')
        ccr = full.get('context_carryover_rate', {}).get('value')
        lines.append(f'BGK xét CCR thay thế: {str(ccr)+"%" if ccr is not None else MISSING}; cần đánh giá của BGK.')
    elif baseline.get('repeat_question_rate', {}).get('value') == 0 and rqr_check['status'] == 'fail':
        lines.append('RQR giảm tương đối: Không xác định (baseline=0, Full>0); không đạt theo BTC.')
    else:
        lines.append(f'RQR giảm tương đối: {str(reduction)+"%" if reduction is not None else MISSING}')
    if voice_measurement:
        lines.append('Response đo từ transcript đến câu trả lời đầy đủ; không gồm prepare, lưu memory, '
                     'ASR/TTS, thời gian phát tiếng hoặc HTTP. TTFT proxy = Response để tương thích '
                     'schema BTC; chưa đo token đầu tiên.')
    elif proxy_ttft:
        lines.append('Chat đo đến câu trả lời đầy đủ, gồm persistence của runtime; '
                     'không gồm prepare, chờ memory worker, ASR/TTS hoặc HTTP. '
                     'TTFT proxy = Total; chưa đo token đầu tiên.')
    elif run.get('conversation_measurement', {}).get('ttft_basis') == 'streaming_guarded_answer_delta':
        lines.append('Chat streaming: TTFT đo tới delta trả lời đầu tiên đã qua kiểm tra tại harness; '
                     'Total gồm hoàn tất nội dung và persistence. Prepare và chờ worker được đo riêng.')
    elif run.get('conversation_measurement', {}).get('ttft_basis') == 'nonstreaming_total_btc_rule_7':
        lines.append('Chat không streaming: TTFT = Total theo quy tắc 7 trong hướng dẫn latency BTC. '
                     'Response gồm persistence của runtime; prepare và chờ worker được đo riêng.')
    for label, key in [('RQR giảm ≥40%', 'meets_rqr_threshold_40pct'),
                       ('TSR ≥70%', 'meets_tsr_70pct'), ('HR giá/KM ≤5%', 'meets_hr_price_5pct')]:
        value = score.get('comparison', {}).get(key)
        status = ('KHÔNG ÁP DỤNG — BGK xét CCR' if key == 'meets_rqr_threshold_40pct'
                  and rqr_check['status'] == 'not_applicable'
                  else 'ĐẠT' if value is True else 'CHƯA ĐẠT' if value is False else MISSING)
        lines.append(f'{label}: {status}')
    if not run.get('latency_scale_sufficient'):
        lines.append('Chưa đủ ≥100 lượt/cấu hình để đánh giá p95 theo hướng dẫn BTC.')
    if run.get('extraction_status') != 'complete':
        lines.append('Extractor còn cần rà soát; không coi claim chưa phân giải là đúng.')
    root = Path(btc_root) if btc_root is not None else Path(run.get('btc_root', directory/'btc-release'))
    if (root/'eval/reference_eval.py').is_file():
        from eval_harness.m1_acceptance import inspect_run
        acceptance = inspect_run(directory, btc_root=root)
        jury_only = (not acceptance['conversation_accepted'] and bool(acceptance['checks'])
                     and all(c['status'] in {'pass', 'not_applicable'} for c in acceptance['checks']))
        verdict = 'ĐẠT' if acceptance['conversation_accepted'] else 'CẦN BGK XÉT CCR' if jury_only else 'CHƯA ĐẠT'
        lines.extend(['', f'Nghiệm thu hội thoại M1: {verdict}'])
        for check in acceptance['checks']:
            if check['status'] != 'pass':
                lines.append(f'- {check["name"]}: {check["status"]}; '
                             f'{json.dumps(check["evidence"], ensure_ascii=False)}')
    else:
        lines.append('Nghiệm thu hội thoại M1: CHƯA KIỂM CHỨNG — thiếu BTC snapshot; truyền --btc-root.')
    lines.append('validated chỉ xác nhận pipeline; hoàn thành M1 còn cần ASR, vòng cải tiến, demo và chi phí.')
    if asr_sources:
        from eval_harness.asr_evidence import collect_asr_evidence
        lines.extend(_asr_lines(collect_asr_evidence(asr_sources, btc_root=root), root))
    elif (directory/'asr_evidence.json').is_file():
        try:
            evidence = json.loads((directory/'asr_evidence.json').read_text())
        except (OSError, ValueError):
            evidence = {}
        lines.extend(_asr_lines(evidence, root))
    lines.append('CCR không phải tỷ lệ fact đã lưu/đọc thành công; thiếu ghi nhận sử dụng không tự chứng minh memory quên.')
    lines.append('HR BTC đối chiếu ground_truth_facts; một sai lệch không tự chứng minh agent bịa thông tin.')
    notes = _claim_mismatch_notes(directory, run, score)
    if notes:
        lines.extend(['', 'Đối chiếu quote cho các ví dụ HR được lưu (không điều chỉnh điểm BTC):', '', *notes, ''])
    lines.append('Bảng đọc nguyên số từ btc_score.json; không phải một lần eval mới.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Display saved BTC scores and verify evidence without models, DB access or mutation.')
    parser.add_argument('run', type=Path, help='Thư mục run hoặc file run.json')
    parser.add_argument('--btc-root', type=Path, help='BTC snapshot dùng để kiểm nghiệm thu hội thoại')
    from eval_harness.asr_evidence import add_asr_arguments, asr_sources_from_args
    add_asr_arguments(parser)
    args = parser.parse_args()
    directory = args.run.parent if args.run.is_file() else args.run
    try:
        print(render_run(directory, btc_root=args.btc_root, asr_sources=asr_sources_from_args(args)))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
