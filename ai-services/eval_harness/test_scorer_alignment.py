import importlib.util
from pathlib import Path

import pytest

from eval_harness.scorer import evaluate_task_success, evaluate_guardrails


def btc_scorer():
    path = Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS/eval/reference_eval.py"
    spec = importlib.util.spec_from_file_location("btc_alignment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quote_confirmation_is_allowed_once_but_repetition_is_redundant():
    from eval_harness.extractor import extract_questions
    questions = extract_questions('Mình đồng ý báo giá này để em lên đơn không ạ?')
    scenarios = {'CASE': {'calls': {'call_2': {'must_not_ask': ['price_quoted_vnd']}}}}
    scorer = btc_scorer()
    one = {('CASE', 'call_2'): [{'turn': 1, 'questions': questions}]}
    assert scorer.repeat_question_rate(scenarios, one)['redundant'] == 0
    two = {('CASE', 'call_2'): [{'turn': turn, 'questions': questions} for turn in (1, 2)]}
    result = scorer.repeat_question_rate(scenarios, two)
    assert result['redundant'] == 1
    assert result['total_questions'] == 2


def test_color_question_uses_btc_slot_and_is_penalized_when_already_known():
    from eval_harness.extractor import extract_questions
    questions = extract_questions('Chị muốn chọn màu nào ạ?')
    scenarios = {'CASE': {'calls': {'call_2': {'must_not_ask': ['color']}}}}
    trace = {('CASE', 'call_2'): [{'turn': 1, 'questions': questions}]}
    assert btc_scorer().repeat_question_rate(scenarios, trace)['redundant'] == 1


@pytest.mark.parametrize("origin,action,passed", [
    ("earlier", "exchange_size", True),
    ("other_scenario", "exchange_size", False),
    ("future", "exchange_size", False),
    ("earlier", "return", False),
])
def test_dynamic_order_alias_matches_btc(origin, action, passed):
    scenarios = {"CASE": {"calls": {"call_1": {}, "call_2": {"success_if": {
        "tool_called": "order.update", "args_match": {
            "order_id": "fixture-order", "action": "exchange_size"}}}, "call_3": {}}}}
    trace = {("CASE", "call_2"): [{"tool_calls": [{"name": "order.update", "args": {
        "order_id": "generated-order", "action": action}}]}]}
    key = {"earlier": ("CASE", "call_1"), "future": ("CASE", "call_3"),
           "other_scenario": ("OTHER", "call_1")}[origin]
    trace[key] = [{"tool_calls": [{"name": "order.create", "result": {
        "order_id": "generated-order"}}]}]
    assert evaluate_task_success(scenarios, trace)["passed"] == int(passed)
    assert btc_scorer().task_success_rate(scenarios, trace)["passed"] == int(passed)


@pytest.mark.parametrize("outcome,total", [("chuyen_may", 0), ("chuyen_nhan_vien", 1)])
def test_handoff_label_matches_btc(outcome, total):
    scenarios = {"CASE": {"calls": {"call_1": {"expected_outcome": outcome}}}}
    trace = {("CASE", "call_1"): [{"tool_calls": [{"name": "handoff.transfer"}]}]}
    assert evaluate_guardrails(scenarios, trace)["total_violations"] == total
    assert btc_scorer().guardrail_violations(scenarios, trace)["total"] == total
