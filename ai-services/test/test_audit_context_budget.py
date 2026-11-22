import json
from unittest.mock import AsyncMock

from app.agent.harness.context import prompt_context
from app.agent.harness.authorization import authorize_write
from test_business_completion import state
import asyncio


def test_long_context_is_bounded_with_explicit_omission_and_preserved_current_input():
    current = state()
    current['customer_statements'] = [{'source_turn_id': str(i), 'customer': 'x'*1000} for i in range(2000)]
    current['current_episode'] = {'session_id': str(current['request'].session_id),
        'topics': [{'topic_id': 'T', 'customer_goal': 'Giữ ngân sách tổng 5 triệu', 'items': []}]}
    visible = prompt_context(current, 6)
    assert len(json.dumps(visible, ensure_ascii=False)) < 70000
    assert visible['customer_text'] == current['safe_text']
    assert '5 triệu' in str(visible['current_episode'])
    assert visible['context_completeness']['complete'] is False
    model = AsyncMock()
    assert asyncio.run(authorize_write(model, current, 'order.create', {}, 6)) is False
    model.with_structured_output.assert_not_called()
