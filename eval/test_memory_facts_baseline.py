"""Checks for the fixed, synthetic memory evaluation corpus and scorer."""

from pathlib import Path

from eval.memory_facts_baseline import load_cases, score


DATASET = Path(__file__).with_name("memory_facts_v1.jsonl")


def test_memory_corpus_has_50_labeled_turns_and_independent_negative_cases():
    cases = load_cases(DATASET)
    assert len(cases) == 50
    assert len({case["id"] for case in cases}) == 50
    assert sum(bool(case["open_facts"]) for case in cases) >= 15
    assert sum(bool(case.get("exclude_reason")) for case in cases) >= 7
    assert {case["input_mode"] for case in cases} == {
        "clean", "chat_teencode", "asr_transcript"}
    assert all(case["text"] for case in cases)


def test_memory_scorer_counts_wrong_value_as_both_false_positive_and_miss():
    rows = [
        {"expected_slots": {"has_children": True},
         "predicted_slots": {"has_children": 1}},
        {"expected_slots": {"budget_vnd": 5_000_000},
         "predicted_slots": {"budget_vnd": 5_000_000, "payment": "COD"}},
    ]
    result = score(rows)
    assert (result["tp"], result["fp"], result["fn"]) == (1, 2, 1)
