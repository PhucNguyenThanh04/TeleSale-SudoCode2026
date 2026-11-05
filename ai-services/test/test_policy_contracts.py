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


def test_cloudflare_runtime_contract_has_no_local_model_or_credentials():
    from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig
    from test_policy_embedding import runtime_config
    config = runtime_config()
    data = config.model_dump()
    assert data['provider'] == 'cloudflare'
    assert data['model_name'] == '@cf/baai/bge-m3'
    assert not {'device', 'dtype', 'model_revision', 'sparse_threshold'} & data.keys()
    assert not {'cloudflare_api_token', 'api_token', 'cloudflare_account_id'} & data.keys()
    assert config.fingerprint() != config.model_copy(update={'bm25_b': .5}).fingerprint()


def test_cloudflare_settings_optional_and_mask_token(monkeypatch):
    from app.configs import Settings
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'fake-cloudflare-secret')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    settings = Settings(_env_file=None, llm_api_key='fake', llm_model='fake')
    assert settings.cloudflare_account_id == 'a' * 32
    assert settings.cloudflare_api_token.get_secret_value() == 'fake-cloudflare-secret'
    assert 'fake-cloudflare-secret' not in repr(settings)
