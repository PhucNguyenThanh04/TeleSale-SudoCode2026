"""Promotion recall follows verified spoken benefits, not technical-code wording."""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.memory.reported_facts import reported_tool_candidates
from app.agent.memory.deterministic_tool_facts import verified_tool_candidates
from app.agent.memory.store import safe_observations
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates


def promo(code='LOCAL-SAVE', kind='percent', discount=100_000, expiry='2026-11-20'):
    return {'promo_code': code, 'type': kind, 'discount_vnd': discount, 'valid_until': expiry}


def quote(promos=None, *, sku='SKU-LOCAL-A', shipping=False):
    return {'name': 'pricing.get_quote', 'args': {'sku': sku, 'on': '2026-11-08'},
            'result': {'sku': sku, 'list_price_vnd': 1_000_000, 'final_price_vnd': 900_000,
                       'applied_promos': promos if promos is not None else [promo()],
                       'freeship': shipping}}


def facts(answer, calls):
    return {(item.get('scope_id'), item['key'], item['value'])
            for item in reported_tool_candidates(answer, calls)
            if item['key'] in {'promo_code', 'promo_expiry'}}


@pytest.mark.parametrize('answer,offer,shipping', [
    ('Mẫu này được giảm 10% đến ngày 20/11 ạ.', promo(), False),
    ('Mẫu này được giảm 100k ạ.', promo(kind='fixed'), False),
    ('Mẫu này tiết kiệm 100.000đ ạ.', promo(kind='fixed'), False),
    ('Mẫu này được miễn phí vận chuyển ạ.', promo(kind='freeship', discount=0), True),
    ('Mẫu này được freeship ạ.', promo(kind='freeship', discount=0), True),
    ('Mẫu này áp dụng LOCAL-SAVE ạ.', promo(), False),
    ('Mẫu này được tặng màng lọc ạ.', promo(kind='gift', discount=0), False),
])
def test_communicated_benefit_records_its_code_and_tool_deadline(answer, offer, shipping):
    assert facts(answer, [quote([offer], shipping=shipping)]) == {
        ('SKU-LOCAL-A', 'promo_code', 'LOCAL-SAVE'),
        ('SKU-LOCAL-A', 'promo_expiry', '2026-11-20')}


@pytest.mark.parametrize('answer', [
    'Mẫu này được giảm 30% ạ.', 'Mẫu này giảm 200k ạ.',
    'Mẫu này có giảm 10% không ạ?', 'Mẫu này áp dụng LOCAL-SAVE không ạ?',
    'Mẫu này không được giảm 10% ạ.', 'Mẫu này không áp dụng LOCAL-SAVE ạ.',
    'Em sẽ kiểm tra ưu đãi hiện tại ạ.', 'Giá mẫu này 900k ạ.',
    'Mẫu này có ưu đãi ạ.', 'Mẫu này được giảm 10% đến ngày 30/11 ạ.',
    'Em kiểm tra xem mẫu này có giảm 10% ạ.',
    'Nếu được giảm 10% thì chị mua nhé.',
    'Mẫu này giảm 10% đến ngày 2026-11-30.',
    'Mẫu này áp dụng LOCAL-SAVE-PLUS ạ.',
])
def test_uncommunicated_or_unsupported_promotion_is_not_a_fact(answer):
    assert facts(answer, [quote()]) == set()


def test_ambiguous_identical_discounts_need_an_explicit_code():
    offers = [promo(), promo('OTHER-SAVE', expiry='2026-11-25')]
    assert facts('Mẫu này được giảm 10%.', [quote(offers)]) == set()
    assert facts('Mẫu này áp dụng OTHER-SAVE, giảm 10%.', [quote(offers)]) == {
        ('SKU-LOCAL-A', 'promo_code', 'OTHER-SAVE'),
        ('SKU-LOCAL-A', 'promo_expiry', '2026-11-25')}


def test_shipping_is_not_attributed_to_an_unrelated_discount_or_default_shipping():
    assert facts('Mẫu này được miễn phí vận chuyển.', [quote(shipping=True)]) == set()
    offers = [promo(), promo('LOCAL-SHIP', 'freeship', 0, '2026-11-30')]
    assert facts('Mẫu này được miễn phí vận chuyển.', [quote(offers, shipping=True)]) == {
        ('SKU-LOCAL-A', 'promo_code', 'LOCAL-SHIP'),
        ('SKU-LOCAL-A', 'promo_expiry', '2026-11-30')}


def test_gift_recognition_survives_a_discount_in_the_same_sentence():
    offers = [promo(), promo('LOCAL-GIFT', 'gift', 0)]
    reported = facts('Mẫu này giảm 10% và tặng màng lọc.', [quote(offers)])
    assert ('SKU-LOCAL-A', 'promo_code', 'LOCAL-GIFT') in reported
    assert ('SKU-LOCAL-A', 'promo_code', 'LOCAL-SAVE') in reported


def test_deadline_and_product_cannot_be_borrowed_from_another_offer():
    offers = [promo(), promo('LOCAL-SHIP', 'freeship', 0, '2026-11-30')]
    assert facts('Mẫu này giảm 10% đến ngày 30/11.', [quote(offers, shipping=True)]) == set()
    calls = [quote(), quote([promo('OTHER-TEN')], sku='SKU-LOCAL-B')]
    assert facts('SKU-LOCAL-B được giảm 10% ạ.', calls) == {
        ('SKU-LOCAL-B', 'promo_code', 'OTHER-TEN'),
        ('SKU-LOCAL-B', 'promo_expiry', '2026-11-20')}
    assert facts('Được giảm 10% ạ.', calls) == set()
    assert facts('SKU-LOCAL-B áp dụng LOCAL-SAVE.', calls) == set()


def test_expired_and_failed_quotes_cannot_supply_active_promotion_facts():
    assert facts('Mẫu này giảm 10%.', [quote([promo(expiry='2026-11-01')])]) == set()
    assert facts('Mẫu này áp dụng LOCAL-SAVE.', [quote([promo(expiry='2026-11-01')])]) == set()
    failed = quote()
    failed['result']['error'] = 'unavailable'
    assert facts('Mẫu này giảm 10%.', [failed]) == set()


def test_verified_promotion_facts_survive_observation_filter_and_admission():
    sid, tid = str(uuid4()), str(uuid4())
    calls = [{**call, 'source_turn_id': tid} for call in safe_observations([quote()])]
    candidates = verified_tool_candidates('Mẫu này giảm 10% ạ.', calls, tid, '2026-11-08')
    accepted, rejected = admit_profile_candidates('C1', sid, candidates, [{
        'customer_id': 'C1', 'session_id': sid, 'turn_id': tid,
        'customer_text': 'Có ưu đãi gì?', 'agent_text': 'Mẫu này giảm 10% ạ.'}], calls)
    assert not rejected
    assert {f['key']: f['value'] for f in accepted} == {
        'promo_code': 'LOCAL-SAVE', 'promo_expiry': '2026-11-20'}
    assert all(f['scope_id'] == 'SKU-LOCAL-A' and f['source_tool'] == 'pricing.get_quote' for f in accepted)
    assert accepted[1]['valid_until'] == '2026-11-20'


def test_only_confirmed_spoken_text_can_supply_promotion_facts():
    assert facts('', [quote()]) == set()
    assert facts('Dạ em kiểm tra giá cho chị.', [quote()]) == set()
    assert facts('Chị có cần không? Mẫu này giảm 10%.', [quote()]) == {
        ('SKU-LOCAL-A', 'promo_code', 'LOCAL-SAVE'),
        ('SKU-LOCAL-A', 'promo_expiry', '2026-11-20')}


def test_single_quote_cannot_describe_another_catalog_product():
    catalog = {'name': 'catalog.search', 'result': {'items': [
        {'sku': 'SKU-LOCAL-A', 'name': 'Máy lọc Local Alpha'},
        {'sku': 'SKU-LOCAL-B', 'name': 'Máy lọc Local Beta'}]}}
    assert facts('Local Beta giảm 10%.', [catalog, quote()]) == set()


def test_promotion_reaches_worker_projection_without_model_extraction():
    asyncio.run(_promotion_reaches_worker_projection())


async def _promotion_reaches_worker_projection():
    from app.mcp_servers.mcp_memory.distiller_worker import process_one

    repo = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield object()

    repo.transaction = transaction
    sid, tid = str(uuid4()), str(uuid4())
    repo.claim_distillation.return_value = {
        'job_id': 9, 'customer_id': 'C1', 'session_id': sid,
        'source_turn_id': tid, 'attempts': 1, 'tool_observations': [quote()]}
    repo.distillation_turn.return_value = {
        'customer_text': 'Có ưu đãi gì?', 'agent_text': 'Mẫu này giảm 10% ạ.',
        'on_date': '2026-11-08', 'channel': 'hotline'}
    repo.is_erasure_blocked.return_value = False
    projection = AsyncMock()
    projection.list_fact_versions.return_value = []
    projection.list_episode_versions.return_value = []
    extractor = AsyncMock(return_value=([], None))
    assert await process_one(repo, extractor, projection)
    stored = projection.put_facts.await_args.args[4]
    assert {f['key']: f['value'] for f in stored
            if f['key'] in {'promo_code', 'promo_expiry'}} == {
        'promo_code': 'LOCAL-SAVE', 'promo_expiry': '2026-11-20'}
    assert all(f['source_tool'] == 'pricing.get_quote' and f['scope_id'] == 'SKU-LOCAL-A'
               for f in stored if f['key'] in {'promo_code', 'promo_expiry'})
    extractor.assert_awaited_once()
