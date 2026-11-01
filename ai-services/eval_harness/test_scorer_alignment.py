"""Synthetic contracts shared with the current BTC scorer; no model or real traces."""
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
