import asyncio

import pytest

from app.mcp_servers.mcp_order.services.order import preview_update, update
from test_order_update_lines import Repo


@pytest.fixture
def repo():
    instance = Repo()
    instance.order.update(created_on='2026-09-25', received_on='2026-09-28')
    try:
        yield instance
    finally:
        instance.close()


def change(repo, on='2026-10-05', action='return', **fields):
    return asyncio.run(update(repo, repo.session, {'order_id': 'LINE-ORDER',
        'action': action, 'on': on, **fields}, 'OWNER-LINES'))


def test_verified_expired_return_does_not_create_a_request(repo):
    result = change(repo, on='2026-11-21')
    assert result.get('error') == 'return_window_expired'
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_missing_condition_evidence_creates_only_a_review_pending_intake(repo):
    result = change(repo)
    assert result['status'] == 'review_pending'
    assert result['estimate'] is True and result['requires_policy_check'] is True
    assert result['eligibility']['status'] == 'pending'
    assert result['eligibility']['missing_fields']
    assert result['refund_days'] == '7 ngày làm việc'


def test_old_policy_preview_preserves_old_exchange_fee_and_refund_period(repo):
    result = asyncio.run(preview_update(repo, repo.session, {'order_id': 'LINE-ORDER',
        'action': 'exchange_product', 'line_index': 0, 'qty': 1,
        'new_variant_sku': 'ITEM-NEW', 'on': '2026-10-05'}, 'OWNER-LINES'))
    assert result['fee_vnd'] == 20000 and result['refund_days'] == '7 ngày làm việc'
    assert result['eligibility']['policy_version'] == '2026-06'
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


@pytest.mark.parametrize('conditions,error', [
    ({'customer_damage': True}, 'return_customer_damage'),
    ({'clearance_no_return': True}, 'return_clearance_excluded'),
    ({'unused': False}, 'return_condition_not_met'),
])
def test_verified_ineligible_conditions_cannot_be_overridden_by_customer_consent(repo, conditions, error):
    repo.order['return_conditions'] = conditions
    assert change(repo).get('error') == error
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_missing_receipt_date_does_not_use_creation_date_as_delivery_evidence(repo):
    repo.order.pop('received_on')
    result = change(repo, on='2026-11-21')
    assert result['status'] == 'review_pending'
    assert 'received_on' in result['eligibility']['missing_fields']


def test_address_changes_keep_the_existing_owned_order_contract(repo):
    result = change(repo, on='2026-11-21', action='update_address', address='Customer destination')
    assert result['status'] == 'updated'


def test_unknown_policy_date_does_not_invent_an_exchange_fee(repo):
    repo.order.pop('created_on')
    result = asyncio.run(preview_update(repo, repo.session, {'order_id': 'LINE-ORDER',
        'action': 'exchange_product', 'line_index': 0, 'new_variant_sku': 'ITEM-NEW',
        'on': '2026-10-05'}, 'OWNER-LINES'))
    assert result['fee_vnd'] is None and result['refund_days'] is None
    assert result['estimated_total_payment_vnd'] is None
    assert result['eligibility']['policy_version'] == 'unverified'


def test_known_eligible_return_can_schedule_pickup_and_opened_hygiene_goods_cannot(repo):
    rows = repo.rows
    repo.order.update(created_on='2026-10-01', received_on='2026-10-03',
        lines=[{'sku': 'SKU-MB-BOT', 'qty': 1, 'price_vnd': 289000}], total_vnd=289000,
        return_conditions={'customer_damage': False, 'clearance_no_return': False,
            'unused': True, 'tags_intact': True, 'packaging_intact': True, 'seal_intact': True})

    async def with_product(session, table):
        if table == 'products':
            return [{'sku': 'SKU-MB-BOT', 'category': 'me-be', 'variants': [], 'attributes': {}}]
        return await rows(session, table)

    repo.rows = with_product
    result = change(repo)
    assert result['status'] == 'pickup_scheduled'
    assert result['eligibility']['status'] == 'eligible'
    repo.order['return_conditions']['seal_intact'] = False
    assert change(repo).get('error') == 'return_hygiene_excluded'
    assert len(asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))) == 1
