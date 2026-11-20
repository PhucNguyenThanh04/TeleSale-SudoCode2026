import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from test_commerce_evidence import state

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs-v2/20261112T071219Z-90613d42'


@pytest.mark.parametrize('turn', [1, 2])
def test_known_customer_empty_order_lookup_does_not_ask_for_unavailable_id(turn):
    rows = list(map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()))
    row = next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T19', 'call_2', turn))
    s = state(row['user_text'])
    calls = []
    async def invoke(name, args, *context, **kwargs):
        calls.append((name, args))
        assert name == 'order.status'
        return {'orders': []}
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={'messages': [AIMessage(content=row['agent_text'])]}))
    async def run():
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=agent), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
            node = AgentNodes(None, SimpleNamespace(invoke_trusted=invoke), None, 5, 6)
            s.update(await node.run_agent(s))
            s.update(await node.verify_agent(s))
        assert 'chưa tìm thấy đơn hàng' in s['agent_text']
        assert 'xin' not in s['agent_text'] and '?' not in s['agent_text']
        assert [name for name, _ in calls] == ['order.status']
        assert agent.ainvoke.await_count == 0
    asyncio.run(run())
