"""The partial November patch must resolve to a reproducible full offline BTC release."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from eval_harness import btc_release

ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT.parent / 'BTC-Data-Vong1-TEAMS'
PATCH = ROOT / 'BTC-cap-nhat-11-2026'


def test_release_combines_exact_patch_and_base_without_changing_sources(tmp_path):
    files = [BTC / 'eval/mock_tools.py', PATCH / 'eval/mock_tools.py']
    before = [p.read_bytes() for p in files]
    release = btc_release.prepare_btc_release(BTC, tmp_path / 'release')
    for relative in ('eval/mock_tools.py', 'eval/reference_eval.py', 'schemas/tools.schema.json'):
        assert (release / relative).read_bytes() == (PATCH / relative).read_bytes()
    assert (release / 'catalog/products.json').read_bytes() == (BTC / 'catalog/products.json').read_bytes()
    assert (release / 'schemas/trace_log.schema.json').is_file()
    spec = importlib.util.spec_from_file_location('resolved_mock', release / 'eval/mock_tools.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])['total_vnd'] > 0
    assert [p.read_bytes() for p in files] == before
    provenance = json.loads((release / 'btc_release.json').read_text())
    assert provenance['patch_files']['eval/reference_eval.py'] == hashlib.sha256(
        (PATCH / 'eval/reference_eval.py').read_bytes()).hexdigest()
    assert btc_release.prepare_btc_release(release, tmp_path / 'unused') == release
    assert not (tmp_path / 'unused').exists()


def test_release_refuses_modified_existing_snapshot(tmp_path):
    release = btc_release.prepare_btc_release(BTC, tmp_path / 'release')
    (release / 'eval/reference_eval.py').write_text('print("stale")')
    with pytest.raises(ValueError, match='btc_release_changed'):
        btc_release.prepare_btc_release(release, tmp_path / 'unused')


def test_resolved_scorer_normalizes_lines_failed_orders_and_timestamps(tmp_path):
    release = btc_release.prepare_btc_release(BTC, tmp_path / 'release')
    spec = importlib.util.spec_from_file_location('resolved_score', release / 'eval/reference_eval.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.args_match({'callback_at': '2026-10-27T09:00', 'promo_code': 'AIR-OCT'},
                             {'callback_at': '2026-10-27T09:00:00'})
    rows = [{'agent_text': '', 'tool_calls': [
        {'name': 'order.create', 'args': {'sku': 'SKU-A', 'price_vnd': 999}, 'result': {'error': 'cod_limit_exceeded'}},
        {'name': 'order.create', 'args': {'lines': [
            {'sku': 'SKU-A', 'qty': 1, 'price_vnd': 100}, {'sku': 'SKU-B', 'qty': 1, 'price_vnd': 50}]},
         'result': {'order_id': 'OD1', 'status': 'created'}}]}]
    assert module.check_call({'success_if': {'tool_called': 'order.create',
        'args_match': {'sku': 'SKU-A', 'price_vnd': 100}, 'also_ordered': ['SKU-B'], 'total_match_vnd': 150}}, rows)[0]
