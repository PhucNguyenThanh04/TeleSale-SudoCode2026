"""Checks for the fixed, synthetic memory evaluation corpus and scorer."""

from pathlib import Path

from eval.memory_facts_baseline import (candidate_diagnostics, load_cases, score,
                                        score_keys, score_normalized_blocker)


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
    assert (score_keys(rows)["tp"], score_keys(rows)["fp"], score_keys(rows)["fn"]) == (2, 1, 0)


def test_blocker_normalization_is_reported_alongside_strict_score():
    rows = [{"expected_slots": {"blocker": "hỏi vợ", "objection": "dat_qua"},
             "predicted_slots": {"blocker": "Tôi phải hỏi vợ đã", "objection": "gia_cao"}}]
    assert (score(rows)["tp"], score(rows)["fp"], score(rows)["fn"]) == (0, 2, 2)
    assert (score_normalized_blocker(rows)["tp"],
            score_normalized_blocker(rows)["fp"],
            score_normalized_blocker(rows)["fn"]) == (1, 1, 1)
    unrelated = [{"expected_slots": {"blocker": "hỏi vợ"},
                  "predicted_slots": {"blocker": "cho vợ"}}]
    assert score_normalized_blocker(unrelated)["tp"] == 0


def test_candidate_diagnostics_reports_rejection_and_masks_pii():
    detail = candidate_diagnostics("Tôi muốn size 42.", [], [
        {"key": "size", "value": "42", "source": "customer"},
        {"key": "blocker", "value": "Gọi 0901234567", "source": "customer"},
    ], [{"key": "size", "value": "43", "source": "customer"}])
    before = detail["before_fact_evidence"]
    assert before[0]["fact_evidence"] == "customer"
    assert before[0]["decision"] == "accepted"
    assert before[1]["value"] == "[REDACTED_PII]"
    assert before[1]["decision"] == "pii_value"
    assert before[2]["decision"] == "pattern_not_matched"
    assert detail["after_fact_evidence"] == [{"key": "size", "value": "42",
                                               "source_kind": "customer"}]


def test_conflicting_evidenced_values_use_closed_reason_code():
    detail = candidate_diagnostics("Tôi hỏi vợ rồi hỏi chồng.", [], [
        {"key": "blocker", "value": "hỏi vợ", "source": "customer"},
        {"key": "blocker", "value": "hỏi chồng", "source": "customer"},
    ], [])
    assert [item["decision"] for item in detail["before_fact_evidence"]] == [
        "conflict", "conflict"]
    assert detail["after_fact_evidence"] == []
