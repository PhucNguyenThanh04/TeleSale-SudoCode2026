from datetime import date
import pytest
from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
from app.knowledge.schemas import SourceChunk


def chunk(**changes):
    return SourceChunk.model_validate(dict(chunk_id='DT-01', section_id='DT-01', document_id='d',
        content='7 ngày', source={'file':'public.md'}, source_hash='s', content_hash='c',
        date_basis='order_date', effective_from='2026-10-01') | changes)


def test_old_and_new_dates_and_reported_date_are_conditional():
    from app.knowledge.policy.rules import apply_policy_rules
    old = chunk(chunk_id='DT-OLD-01', section_id='DT-OLD-01', effective_from=None, effective_until='2026-09-30')
    request = PolicySearchInput(query='đổi trả', on='2026-11-03', customer_reported_order_date='2026-09-20')
    context = TrustedPolicyContext(request_id='r', principal='harness', on=request.on)
    rows = apply_policy_rules([chunk(), old], request, context)
    assert [e.chunk_id for e in rows] == ['DT-OLD-01']
    assert rows[0].applicability.status == 'conditional'
    assert rows[0].applicability.date_source == 'customer_reported'
    verified = context.model_copy(update={'verified_order_date': date(2026,10,1), 'date_source':'order.status:OD-1'})
    rows = apply_policy_rules([chunk(), old], request, verified)
    assert [e.chunk_id for e in rows] == ['DT-01']
    assert rows[0].applicability.status == 'applicable'


def test_missing_date_does_not_use_on_and_conflict_survives():
    from app.knowledge.policy.rules import apply_policy_rules
    request = PolicySearchInput(query='đổi trả', on='2026-11-03')
    context = TrustedPolicyContext(request_id='r', principal='harness', on=request.on)
    rows = apply_policy_rules([chunk(), chunk(chunk_id='XX', conflict=True)], request, context)
    assert rows[0].applicability.date_used is None
    assert rows[0].applicability.required_context == ['order_date']
    assert rows[1].applicability.status == 'conflict'


def test_warranty_exception_is_selected_by_order_date_not_current_date():
    from app.knowledge.policy.source import default_metadata, parse_policy_sources
    from app.knowledge.policy.rules import apply_policy_rules
    from btc_data import btc_data_dir
    bh=next(c for c in parse_policy_sources(btc_data_dir()/'policy',default_metadata()) if c.chunk_id=='BH-01')
    request=PolicySearchInput(query='bảo hành Karofi',on='2026-11-03')
    context=TrustedPolicyContext(request_id='r',principal='harness',on=request.on,
        verified_order_date='2026-07-10',date_source='order.status')
    result=apply_policy_rules([bh],request,context)[0]
    assert result.applicability.status=='conditional'
    assert len(result.applicability.rules)==1
    assert result.applicability.rules[0].effective_until==date(2026,7,31)


def test_all_old_return_sections_keep_expiry_and_prelude():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from btc_data import btc_data_dir
    rows = parse_policy_sources(btc_data_dir()/'policy', default_metadata())
    old = [c for c in rows if c.chunk_id.startswith('DT-OLD-')]
    new = [c for c in rows if c.document_id == 'chinh-sach-doi-tra.md']
    assert len(old) == 5 and len(new) == 7
    assert all(c.effective_until == date(2026,9,30) and c.date_basis == 'order_date' for c in old)
    assert all('tra cứu đơn hàng cũ' in c.content for c in old)
    assert all(c.effective_from == date(2026,10,1) for c in new)


@pytest.mark.parametrize('order_date,expected', [('2026-09-30','DT-OLD-'), ('2026-10-01','DT-')])
def test_return_policy_boundary_uses_verified_order_date(order_date, expected):
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from app.knowledge.policy.rules import apply_policy_rules
    from btc_data import btc_data_dir
    rows = [c for c in parse_policy_sources(btc_data_dir()/'policy', default_metadata()) if c.chunk_id.startswith('DT-')]
    request = PolicySearchInput(query='đổi trả', on='2026-11-03')
    context = TrustedPolicyContext(request_id='fixture', principal='test', on=request.on,
        verified_order_date=order_date, date_source='offline-fixture')
    result = apply_policy_rules(rows, request, context)
    assert {r.chunk_id for r in result} == {c.chunk_id for c in rows if (c.chunk_id.startswith('DT-OLD-') == (expected=='DT-OLD-'))}
    assert all(r.applicability.status == 'applicable' for r in result)


def test_unknown_and_reported_order_dates_never_confirm_entitlement():
    from app.knowledge.policy.rules import apply_policy_rules
    request = PolicySearchInput(query='đổi trả', on='2026-11-03')
    context = TrustedPolicyContext(request_id='test', principal='test', on=request.on)
    assert apply_policy_rules([chunk()], request, context)[0].applicability.date_used is None
    reported = request.model_copy(update={'customer_reported_order_date':date(2026,10,2)})
    assert apply_policy_rules([chunk()], reported, context)[0].applicability.status == 'conditional'
    with pytest.raises(ValueError, match='Unverified'):
        apply_policy_rules([chunk()], request.model_copy(update={'order_date':date(2026,10,2)}), context)


def test_warranty_rule_boundary_is_not_global_document_expiry():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from app.knowledge.policy.rules import apply_policy_rules
    from btc_data import btc_data_dir
    bh = next(c for c in parse_policy_sources(btc_data_dir()/'policy', default_metadata()) if c.chunk_id=='BH-01')
    assert bh.effective_until is None
    request = PolicySearchInput(query='bảo hành', on='2026-11-03')
    for day,until,start in [('2026-07-31',date(2026,7,31),None),('2026-08-01',None,date(2026,8,1))]:
        context = TrustedPolicyContext(request_id='test', principal='test', on=request.on,
            verified_order_date=day, date_source='offline-fixture')
        rules = apply_policy_rules([bh],request,context)[0].applicability.rules
        assert len(rules)==1 and rules[0].effective_until==until and rules[0].effective_from==start


def test_unspecified_expiry_is_present_null_not_invented():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from btc_data import btc_data_dir
    row = next(c for c in parse_policy_sources(btc_data_dir()/'policy', default_metadata()) if c.chunk_id=='SP-SN-01')
    assert row.model_dump()['effective_until'] is None


@pytest.mark.parametrize('kind', ['chunk','rule'])
def test_invalid_date_interval_is_rejected(kind):
    from app.knowledge.schemas import PolicyRule
    with pytest.raises(ValueError, match='interval'):
        if kind == 'chunk':
            chunk(effective_from='2026-10-02', effective_until='2026-10-01')
        else:
            PolicyRule(scope='test', effective_from='2026-10-02', effective_until='2026-10-01')
    with pytest.raises(ValueError):
        chunk(effective_from='2026-02-30')
