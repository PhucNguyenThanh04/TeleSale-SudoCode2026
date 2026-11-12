"""Policy recovery must survive the real preceding sales evidence."""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from test_commerce_evidence import state
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_followup_reply
from app.agent.guardrails.checks import check_answer
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs/20261112T060044Z-17ffa366'


@pytest.mark.parametrize('sid,on', [('SC-T19', '2026-10-21'), ('SC-T22', '2026-10-20')])
def test_policy_recovery_with_prior_product_quote_answers_policy(sid, on):
    rows = list(map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()))
    prior, row = [next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) ==
                     (sid, 'call_1', turn)) for turn in (1, 2)]
    s = state(row['user_text'])
    s['request'] = s['request'].model_copy(update={'on': date.fromisoformat(on)})
    s.update(tool_calls=row['tool_calls'], session_tool_calls=prior['tool_calls'], followup_kind='policy')
    answer = safe_followup_reply(s)
    assert 'giá hiện tại' not in answer
    assert check_answer(answer, build_commerce_evidence(s), s['safe_text'])[1] is None
    s['agent_draft'] = 'Sản phẩm này có giá 123.000đ.'
    verified = asyncio.run(AgentNodes(None, None, None, 8, 6).verify_agent(s))['agent_text']
    assert 'giá hiện tại' not in verified
    assert ('8%' in verified and '35.000' in verified) if sid == 'SC-T19' else '7 ngày' in verified
    from app.agent.harness.session_nodes import safe_quote_reply
    s['agent_draft'] = safe_quote_reply(s)
    assert s['agent_draft'] and check_answer(s['agent_draft'], build_commerce_evidence(s), s['safe_text'])[1] is None
    verified = asyncio.run(AgentNodes(None, None, None, 8, 6).verify_agent(s))['agent_text']
    assert 'giá hiện tại' not in verified
