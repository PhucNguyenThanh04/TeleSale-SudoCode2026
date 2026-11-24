import hashlib
import json
from pathlib import Path

from eval_harness.scenario_contract import load_scenarios


ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT.parent / 'BTC-Data-Vong1-TEAMS'
FINAL = ROOT / 'eval/scenario_final'


def test_final_personas_receipts_semantic_criteria_and_order_shapes():
    cases = load_scenarios(FINAL, btc_root=BTC)
    personas = {p['persona_id'] for p in json.loads((BTC / 'simulator/personas.json').read_text())['personas']}
    assert len(cases) >= 40
    assert all(len(c['calls']) in (2, 3) for c in cases.values())
    for scenario in cases.values():
        assert scenario['persona'] in personas
        for call in scenario['calls'].values():
            assert call['semantic_requirements']
            assert all(r['id'] and r['requirement'] and r['source_sections'] for r in call['semantic_requirements'])
            success = call['success_if']
            if success.get('tool_called') == 'order.status':
                assert success['args_match']['order_id']
            if success.get('tool_called') == 'order.create':
                assert call['supplemental_checks']['order_count'] == 1
                assert all(line['sku'] and type(line['price_vnd']) is int and line.get('qty', 1) >= 1
                           for line in call['supplemental_checks']['order_lines'])
    assert cases['TEAM-15']['calls']['call_2']['must_carry_over'] == []
    assert 'child_weight_kg' in cases['TEAM-29']['calls']['call_2']['must_carry_over']
    assert cases['TEAM-20']['persona'] == 'khach_goi_lan_3_het_kien_nhan'
    assert cases['TEAM-20']['calls']['call_3']['success_if']['max_agent_questions'] == 1
    ids = {c['id'] for c in json.loads((BTC / 'eval/llm_judge_rubric.json').read_text())['criteria']}
    assert {k for s in cases.values() for c in s['calls'].values() for k in c['judge_criteria']} == ids
    shared = cases['TEAM-28']['calls']['call_1']
    assert 'hotline' in shared['semantic_requirements'][0]['requirement']
    assert 'SĐT' in shared['customer_goal']


def test_original_dataset_sources_are_preserved_and_btc_samples_stay_excluded():
    mapping = json.loads((FINAL / '_source_map.json').read_text())
    for item in mapping['scenarios']:
        assert hashlib.sha256((ROOT / item['source']).read_bytes()).hexdigest() == item['source_sha256']
        assert item['original_id'] not in mapping['excluded']
    assert {item['scenario_id'] for item in mapping['scenarios']} <= {
        p.stem for p in FINAL.glob('TEAM-*.json')}


def test_expected_orders_are_accepted_by_unmodified_btc_mock():
    import importlib.util
    cases = load_scenarios(FINAL, btc_root=BTC)
    for scenario in cases.values():
        module_spec = importlib.util.spec_from_file_location('final_btc_mock', BTC / 'eval/mock_tools.py')
        mock = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(mock)
        for name, call in scenario['calls'].items():
            if call['success_if'].get('tool_called') != 'order.create':
                continue
            lines = call['supplemental_checks']['order_lines']
            expected = call['success_if'].get('args_match', {})
            result = mock.order_create(customer_phone=scenario['customer_phone'], lines=lines,
                payment=expected.get('payment', 'COD'), address='Hà Nội', on=call['call_date'])
            assert result.get('status') == 'created', (scenario['scenario_id'], name, result)
            if 'total_match_vnd' in call['success_if']:
                assert result['total_vnd'] == call['success_if']['total_match_vnd']


def test_safety_cases_exercise_real_inputs_and_identity_ambiguity():
    import re
    cases = load_scenarios(FINAL, btc_root=BTC)
    assert len(cases) >= 48
    pii = cases['TEAM-43']['calls']['call_2']
    text = ' '.join(pii['customer_turns'])
    assert re.search(r'\b0\d{11}\b', text)
    assert pii['success_if']['trace_must_not_match']
    assert cases['TEAM-44']['calls']['call_3']['must_carry_over'] == []
    assert any('xóa' in text for text in cases['TEAM-44']['calls']['call_2']['customer_turns'])
    noisy = cases['TEAM-46']['calls']
    assert noisy['call_1']['input_mode'] == 'asr_transcript'
    assert noisy['call_1']['customer_turns_asr'] != noisy['call_1']['customer_turns']
    assert noisy['call_2']['input_mode'] == 'chat_teencode'
    shared = cases['TEAM-28']['calls']['call_1']
    crm = json.loads((BTC / 'catalog/crm_seed.json').read_text())['customers']
    assert shared['channel'] == 'hotline'
    assert sum(c['phone'] == shared['channel_identity'] for c in crm) == 2
    history = cases['TEAM-12']['calls']['call_1']['seed_history']
    assert [{k: v for k, v in h.items() if k != 'facts'} for h in history] == next(c for c in crm if c['customer_id'] == 'C031')['sessions']
    assert history[0]['facts'][0] == {'field': 'room_area_m2', 'value': 20, 'as_of': history[0]['date']}
    assert history[0]['facts'][1]['value'] in history[0]['summary']
    assert cases['TEAM-47']['calls']['call_1']['ground_truth_facts']['historical_return_days'] == 14
    assert cases['TEAM-48']['calls']['call_1']['channel_identity'] not in {c['phone'] for c in crm}


def test_supplemental_labels_cannot_silently_ignore_invalid_rules(tmp_path):
    import pytest
    data = json.loads((FINAL / 'TEAM-23.json').read_text())
    data['calls']['call_2']['supplemental_checks']['order_lines'][0]['qty'] = True
    (tmp_path / 'case.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='supplemental'):
        load_scenarios(tmp_path, btc_root=BTC)


def test_semantic_requirements_need_unique_ids_and_sources(tmp_path):
    import pytest
    data = json.loads((FINAL / 'TEAM-23.json').read_text())
    data['calls']['call_2']['semantic_requirements'] *= 2
    (tmp_path / 'case.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='semantic'):
        load_scenarios(tmp_path, btc_root=BTC)


def test_frozen_manifest_detects_data_and_source_changes(tmp_path):
    import pytest
    from eval_harness.scenario_contract import verify_manifest
    manifest = json.loads((FINAL / '_manifest.json').read_text())
    assert len(manifest['scenarios']) == 48
    for name in manifest['scenarios']:
        (tmp_path / name).write_bytes((FINAL / name).read_bytes())
    for name in manifest['metadata']:
        (tmp_path / name).write_bytes((FINAL / name).read_bytes())
    (tmp_path / '_manifest.json').write_bytes((FINAL / '_manifest.json').read_bytes())
    verify_manifest(tmp_path, BTC)
    (tmp_path / 'TEAM-01.json').write_text('{}')
    with pytest.raises(ValueError, match='hash_mismatch'):
        verify_manifest(tmp_path, BTC)
    (tmp_path / 'TEAM-01.json').unlink()
    with pytest.raises(ValueError, match='file_mismatch'):
        verify_manifest(tmp_path, BTC)


def test_unknown_rubric_ids_are_rejected(tmp_path):
    import pytest
    data = json.loads((FINAL / 'TEAM-23.json').read_text())
    data['calls']['call_1']['judge_criteria'] = ['J99_fake']
    (tmp_path / 'case.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='judge_criteria_invalid'):
        load_scenarios(tmp_path, btc_root=BTC)
