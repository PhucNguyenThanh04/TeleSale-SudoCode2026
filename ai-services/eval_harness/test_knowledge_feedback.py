import pytest


def test_feedback_derives_only_observed_failed_turns_and_preserves_tools():
    from eval_harness.knowledge_feedback import feedback_events
    run = {'run_id': 'r', 'score': {'system': {'task_success_rate': {'failures': [
        {'scenario': 'SC1', 'call': 'call_2', 'reasons': ['không gọi tool']}]}}},
        'rows': [{'scenario_id': 'SC1', 'call': 'call_2', 'turn': 1,
            'customer_text': 'đổi hàng', 'agent_text': 'chưa rõ',
            'tool_calls': [{'name': 'policy.search', 'args': {'query': 'đổi'}}]}]}
    events = feedback_events(run)
    assert len(events) == 1
    assert events[0]['event']['tool_calls'][0]['name'] == 'policy.search'
    assert 'success_if' not in events[0]['event']
    assert events[0]['event']['source'] == 'evaluation_result'


def test_incomplete_run_is_rejected_before_import(tmp_path):
    from eval_harness.knowledge_feedback import load_verified_run
    (tmp_path/'run.json').write_text('{"status":"interrupted"}')
    with pytest.raises(ValueError):
        load_verified_run(tmp_path)
