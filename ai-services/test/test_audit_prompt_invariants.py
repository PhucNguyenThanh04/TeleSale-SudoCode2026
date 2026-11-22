import asyncio
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.implementations.business_agent import _SYSTEM_PROMPT
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


def test_main_prompt_contains_btc_medical_opening_and_order_presentation_rules():
    assert 'PB-06' in _SYSTEM_PROMPT and 'dược sĩ' in _SYSTEM_PROMPT
    assert 'PB-01' in _SYSTEM_PROMPT and 'tối đa 2 thông tin' in _SYSTEM_PROMPT
    assert 'PB-09' in _SYSTEM_PROMPT and 'thời gian giao dự kiến' in _SYSTEM_PROMPT
    assert 'phương thức thanh toán' in _SYSTEM_PROMPT and 'chờ khách đồng ý' in _SYSTEM_PROMPT


def test_repair_reuses_the_exact_selected_prompt_without_a_second_fetch():
    async def run():
        selected = _SYSTEM_PROMPT + '\nMANAGED_CONTRACT_EXAMPLE'
        model = FakeToolModel(replies=[AIMessage(content='Mẫu này giá 3.000.000đ.'),
                                      AIMessage(content='Mình cần tư vấn loại sản phẩm nào ạ?')])
        runtime = DeepHarnessRuntime(model, FakeGateway(), FakeMemory())
        try:
            with patch('app.agent.harness.agent_nodes.text_prompt', return_value=selected) as fetch:
                await runtime.run(turn('Xin tư vấn sản phẩm'))
            assert len(model.seen) == 2
            assert all('MANAGED_CONTRACT_EXAMPLE' in messages for messages in model.seen)
            fetch.assert_called_once()
        finally:
            await runtime.close()
    asyncio.run(run())
