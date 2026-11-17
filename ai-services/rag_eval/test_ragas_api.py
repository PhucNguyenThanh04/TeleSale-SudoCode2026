"""Optional pinned-Ragas API test: all HTTP is served by MockTransport."""
import asyncio
import importlib.util
import json

import pytest


@pytest.mark.skipif(importlib.util.find_spec('ragas') is None, reason='optional Ragas dependency not installed')
def test_pinned_ragas_judge_against_fake_http(monkeypatch):
    monkeypatch.setenv('RAGAS_DO_NOT_TRACK', 'true')
    import httpx
    from rag_eval.judging import JudgeSettings, RagasJudge
    calls = []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        prompt = json.dumps(payload['messages'], ensure_ascii=False)
        if 'restricted_leak' in prompt:
            content = {'correct': True, 'action': 'answer', 'version_correct': None,
                       'numeric_correct': None, 'restricted_leak': False, 'reason': 'Có nguồn.'}
        elif 'ClaimDecompositionOutput' in prompt:
            content = {'claims': ['Đổi hàng trong 7 ngày.']}
        elif 'StatementGeneratorOutput' in prompt:
            content = {'statements': ['Đổi hàng trong 7 ngày.']}
        else:
            content = {'statements': [{'statement': 'Đổi hàng trong 7 ngày.',
                                       'reason': 'Có trong nguồn.', 'verdict': 1}]}
        return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion',
            'created': 0, 'model': 'offline', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': json.dumps(content, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    async def check():
        judge = RagasJudge(JudgeSettings(_env_file=None, model='offline',
            api_key='offline-key', base_url='http://offline.invalid/v1'))
        await judge.client._client.aclose()
        judge.client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        case = {'input': {'query': 'Đổi hàng trong bao lâu?'}, 'labels': {
            'type': 'single', 'expected_answer': 'Đổi hàng trong 7 ngày.', 'relevant_chunk_ids': ['DT-01']}}
        row = {'answer': 'Đổi hàng trong 7 ngày.', 'generation_input': {
            'business_context': {'on': '2026-10-15'},
            'policy_evidence': [{'content': 'Đổi hàng trong 7 ngày.'}],
            'reference_tool_observations': []}}
        try:
            assert (await judge.business(case, row))['correct'] is True
            assert await judge.faithfulness(case, row) == 1
            assert await judge.factual_correctness(case, row) == 1
        finally:
            await judge.close()
    asyncio.run(check())
    assert len(calls) == 7  # business + 2 faithfulness + 4 correctness requests
