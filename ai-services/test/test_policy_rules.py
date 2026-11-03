from datetime import date
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
    assert result.applicability.status=='conditional'  # Product/conditions still require confirmation.
    assert len(result.applicability.rules)==1
    assert result.applicability.rules[0].effective_until==date(2026,7,31)
