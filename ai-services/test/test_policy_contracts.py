import pytest
from pydantic import ValidationError


def test_contract_rejects_blank_query_invalid_date_and_top_k():
    from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput
    for extra in ({'query': '  '}, {'on': '03/11/2026'}, {'top_k': 0}, {'top_k': 11}, {'access': 'admin'}):
        with pytest.raises(ValidationError):
            PolicySearchInput.model_validate({'query': 'đổi trả', 'on': '2026-11-03'} | extra)
    assert PolicySearchInput(query=' đổi trả ', on='2026-11-03').query == 'đổi trả'


def test_reported_date_never_becomes_verified_order_date():
    from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
    request = PolicySearchInput(query='đổi trả', on='2026-11-03', customer_reported_order_date='2026-09-20')
    assert request.order_date is None
    context = TrustedPolicyContext(request_id='r', principal='harness', on='2026-11-03')
    with pytest.raises(ValidationError):
        context.model_copy(update={}).__class__.model_validate(context.model_dump() | {'access': 'admin'})


def test_complete_dependencies_do_not_certify_answer():
    from app.knowledge.schemas import EvidenceSet
    from app.mcp_servers.mcp_knowledge.schemas import PolicySearchResult
    result = PolicySearchResult(retrieval_status='ok', context={'on': '2026-11-03'})
    assert result.evidence_set == EvidenceSet(required_dependencies_complete=True)
    assert result.evidence == []
    assert result.truncated is False


def test_missing_dependency_is_attached_to_affected_evidence():
    from app.knowledge.schemas import Evidence, Applicability
    row = Evidence(chunk_id='DT-01', section_id='DT-01', document_id='doc', content='7 ngày',
                   source={'file': 'public.md'}, applicability=Applicability(status='conditional',
                   missing_required_section_ids=['CL-01']))
    assert row.applicability.missing_required_section_ids == ['CL-01']
    assert row.evidence_type == 'business_rule'
