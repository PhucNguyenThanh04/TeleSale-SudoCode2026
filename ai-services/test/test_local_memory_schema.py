"""Local memory extraction cannot invent deterministic consultation state."""
import asyncio
from datetime import date
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.configs import Settings
from app.infarstructure.llm import build_llm
from app.agent.memory.langmem_extractor import extract_candidates
from app.schemas.langmem import CustomerCallEpisodeCandidate, ProfileFactCandidate


def episode_schema(backend):
    captured = []

    class Manager:
        async def ainvoke(self, payload):
            return []

    def create(model, *, schemas, **kwargs):
        captured.extend(schemas)
        return Manager()

    model = build_llm(Settings(_env_file=None, llm_backend=backend,
                              llm_api_key='offline', llm_model='offline'))
    with patch('app.agent.memory.langmem_extractor.create_memory_manager', create):
        asyncio.run(extract_candidates(model, [], []))
    assert captured[0] is ProfileFactCandidate
    return captured[1]


def test_local_episode_schema_excludes_canonical_consultation_but_preserves_evidence():
    schema = episode_schema('local')
    wire = schema.model_json_schema()
    assert 'ConsultationSnapshot' not in wire.get('$defs', {})
    value = schema(customer_id='C1', session_id='S1', channel='hotline', on=date(2026, 11, 9),
                   source_turn_ids=['T1'], topics=[{'scope_type': 'product', 'scope_id': 'LOCAL-A',
                       'advice_given': {'text': 'Tư vấn LOCAL-A', 'evidence_quote': 'Em tư vấn mẫu LOCAL-A'}}])
    assert isinstance(value, CustomerCallEpisodeCandidate)
    assert value.topics[0].advice_given.evidence_quote == 'Em tư vấn mẫu LOCAL-A'
    assert value.topics[0].consultation is None
    with pytest.raises(ValidationError):
        schema(**{**value.model_dump(), 'topics': [{'consultation': {'schema_version': 1}}]})


def test_cloud_keeps_original_episode_schema():
    assert episode_schema('api') is CustomerCallEpisodeCandidate


def test_real_langmem_manager_sends_constrained_local_schemas_and_returns_typed_facts():
    import json
    import httpx2 as httpx

    model = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []
    fact = {'key': 'budget_vnd', 'value': 5000000, 'op': 'set', 'scope_type': 'global',
            'scope_id': '', 'source_kind': 'customer', 'source_turn_id': 'T1',
            'evidence_quote': 'Ngân sách của tôi là 5 triệu', 'observed_on': '2026-11-09'}

    async def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={
            'id': 'memory-test', 'object': 'chat.completion', 'created': 0,
            'model': 'local', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                'message': {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'fact-call', 'type': 'function', 'function': {
                        'name': 'ProfileFactCandidate', 'arguments': json.dumps(fact)}}]}}]})

    with patch.object(httpx.AsyncClient, 'send', send):
        facts, episode = asyncio.run(extract_candidates(model, [], []))
    assert len(requests) == 1
    assert 'parallel_tool_calls' not in requests[0]
    assert all(tool['function']['strict'] for tool in requests[0]['tools'])
    episode_tool = next(tool for tool in requests[0]['tools']
                        if tool['function']['name'] == 'LocalCallEpisodeCandidate')
    topic = episode_tool['function']['parameters']['properties']['topics']['items']
    if '$ref' in topic:
        topic = episode_tool['function']['parameters']['$defs'][topic['$ref'].rsplit('/', 1)[-1]]
    assert topic['properties']['consultation']['type'] == 'null'
    assert facts[0].key == 'budget_vnd' and facts[0].value == 5000000
    assert episode is None
