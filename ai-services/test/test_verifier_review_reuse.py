import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from test_semantic_grounding import ReviewModel, turn_state, verdict


class EvidenceReviewer:
    def __init__(self):
        self.payloads = []
        self.ainvoke = AsyncMock(return_value=AIMessage(content='Thiết bị hỗ trợ Zigbee.'))

    def with_structured_output(self, schema, **kwargs):
        async def review(messages):
            payload = json.loads(messages[-1].content)
            self.payloads.append(payload)
            supported = (payload['answer'] == 'Thiết bị hỗ trợ Zigbee.'
                         or len(payload['context']['tool_observations']) > 1)
            return verdict() if supported else verdict(False, 'customer_constraint_violated', payload['answer'])
        return SimpleNamespace(ainvoke=review)


def test_unchanged_rejected_draft_is_reviewed_once_before_answer_repair():
    draft = 'Mẫu này đáp ứng yêu cầu kết nối Wi-Fi của chị.'
    state = turn_state(draft)
    state['safe_text'] = 'Chị cần kết nối Wi-Fi.'
    state['agent_continuation'] = AsyncMock(return_value=draft)
    model = EvidenceReviewer()
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == 'Thiết bị hỗ trợ Zigbee.'
    assert [payload['answer'] for payload in model.payloads] == [draft, 'Thiết bị hỗ trợ Zigbee.']


def test_same_draft_is_reviewed_again_after_continuation_adds_evidence():
    draft = 'Mẫu này đáp ứng yêu cầu kết nối Wi-Fi của chị.'
    state = turn_state(draft)
    state['safe_text'] = 'Chị cần kết nối Wi-Fi.'

    async def continuation(current, answer, reason):
        details = deepcopy(current['tool_calls'][0]['result'])
        details['items'][0]['attributes']['connectivity'] = 'Wi-Fi'
        current['tool_calls'].append({'name': 'catalog.get_details', 'args': {'sku': 'DEVICE-81'},
            'result': details})
        return answer

    state['agent_continuation'] = continuation
    model = EvidenceReviewer()
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == draft
    assert len(model.payloads) == 2
    assert [len(p['context']['tool_observations']) for p in model.payloads] == [1, 2]
    model.ainvoke.assert_not_awaited()


def test_unavailable_review_does_not_trigger_answer_only_repair():
    draft = 'Thiết bị hỗ trợ Zigbee.'
    model = ReviewModel([TimeoutError('temporary'), verdict()], draft)
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(draft)))
    assert result['verified_answer'] == draft
    assert len(model.payloads) == 1
    model.ainvoke.assert_not_awaited()


def test_review_reuse_never_crosses_verifier_invocations():
    draft = 'Mẫu này đáp ứng yêu cầu kết nối Wi-Fi của chị.'
    model = EvidenceReviewer()
    node = AgentNodes(model, None, None, 8, 6)

    async def run():
        for _ in range(2):
            state = turn_state(draft)
            state['safe_text'] = 'Chị cần kết nối Wi-Fi.'
            state['agent_continuation'] = AsyncMock(return_value=draft)
            assert (await node.verify_agent(state))['verified_answer'] == 'Thiết bị hỗ trợ Zigbee.'

    asyncio.run(run())
    assert len(model.payloads) == 4
