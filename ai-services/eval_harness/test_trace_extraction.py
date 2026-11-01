"""Hand-labeled synthetic examples for the BTC trace fields we generate."""

import json
from pathlib import Path

from eval_harness.extractor import extract_claims, extract_questions
from eval_harness.reference_adapter import facts_used, trace_line


LABELS = json.loads((Path(__file__).parent / "fixtures" /
                     "text_extraction_labels.json").read_text(encoding="utf-8"))


def test_annotated_questions_match_slot_and_type():
    for case in LABELS["questions"]:
        actual = [{"slot": item["slot"], "type": item["type"]}
                  for item in extract_questions(case["text"])]
        assert actual == case["expected"], case["text"]


def test_annotated_claims_exclude_customer_budget():
    for case in LABELS["claims"]:
        actual = [{"field": item["field"], "value": item["value"]}
                  for item in extract_claims(case["text"], [])]
        assert actual == case["expected"], case["text"]


def test_boolean_fact_use_requires_matching_polarity_and_prior_source():
    prior_true = {"has_children": {"value": True, "source": "old-session:turn-1"}}
    prior_false = {"has_children": {"value": False, "source": "old-session:turn-1"}}
    current = {"has_children": {"value": True, "source": "current:turn-2"}}
    assert facts_used("Vì nhà mình có trẻ nhỏ, mẫu này có khóa an toàn.", [],
                      prior_true, current_session_id="current") == ["has_children"]
    assert facts_used("Vì nhà mình không có trẻ nhỏ, mình chọn mẫu khác.", [],
                      prior_true, current_session_id="current") == []
    assert facts_used("Vì nhà mình không có trẻ nhỏ, mình chọn mẫu khác.", [],
                      prior_false, current_session_id="current") == ["has_children"]
    assert facts_used("Vì nhà mình có trẻ nhỏ, mẫu này có khóa an toàn.", [],
                      current, current_session_id="current") == []
    assert facts_used("Dạ em kiểm tra tiếp ạ.", [
        {"name": "catalog.search", "args": {"include_discontinued": True}}],
        prior_true, current_session_id="current") == []


VALID_BTC_TOOLS = {
    "crm.get_customer", "catalog.search", "inventory.check", "pricing.get_quote",
    "order.create", "order.update", "order.status", "handoff.transfer",
    "schedule.callback", "policy.search"
}


def test_trace_preserves_valid_tool_names_and_exact_business_args():
    raw_calls = [
        {"name": "order.create", "args": {
            "sku": "SKU-AP-Y", "price_vnd": 5200000, "payment": "COD",
            "customer_phone": "0984726714", "customer_name": "Hoa",
            "address": "12 Lê Lợi"
        }},
        {"name": "handoff.transfer", "args": {
            "reason": "gdpr_erasure", "brief": {"note": "xóa dữ liệu"}
        }},
        {"name": "catalog.search", "args": {"query": "RunLite"}},
    ]
    row = trace_line("run", "full", "SC01", "call_1", 1,
                     "Tôi muốn mua", "Dạ được ạ",
                     raw_calls, [], [], 100, None, "clean", customer_name="Hoa")
    for call in row["tool_calls"]:
        assert call["name"] in VALID_BTC_TOOLS, f"Invalid tool name: {call['name']}"
    # Verify exact business arguments are NOT masked
    order_call = row["tool_calls"][0]
    assert order_call["name"] == "order.create"
    assert order_call["args"]["sku"] == "SKU-AP-Y"
    assert order_call["args"]["price_vnd"] == 5200000
    assert order_call["args"]["payment"] == "COD"
    # Verify PII is masked or dropped
    assert order_call["args"]["customer_phone"] == "[SỐ ĐÃ ẨN]"
    assert order_call["args"]["customer_name"] == "[TÊN ĐÃ ẨN]"
    assert "address" not in order_call["args"]


def test_trace_preserves_every_tool_name_call_id_and_unrelated_fields():
    raw_calls = [
        {"name": "catalog.search", "id": "call-1", "args": {
            "query": "RunLite", "metadata": {"customer_name": "business-label"}}},
        {"name": "order.create", "id": "call-2", "args": {
            "sku": "SKU-A", "customer_name": "Hoa"}},
    ]
    row = trace_line("run", "full", "S01", "call_1", 1,
                     "Tôi tên Hoa.", "Dạ", raw_calls, [], [], 10, None,
                     "clean", customer_name="Hoa")
    assert [call["name"] for call in row["tool_calls"]] == [
        "catalog.search", "order.create"]
    assert [call["id"] for call in row["tool_calls"]] == ["call-1", "call-2"]
    assert row["tool_calls"][0]["args"]["metadata"]["customer_name"] == "business-label"
    assert row["tool_calls"][1]["args"]["customer_name"] == "[TÊN ĐÃ ẨN]"


def test_trace_preserves_business_order_id_with_long_numeric_suffix():
    raw_calls = [{"name": "order.update", "id": "call-1", "args": {
        "order_id": "OD1234567890", "action": "exchange_size",
        "new_variant_sku": "SKU-SN-CAS-40-DEN"},
        "result": {"order_id": "OD1234567890"}}]
    row = trace_line("run", "full", "S01", "call_2", 1,
                     "Đổi size giúp tôi", "Dạ", raw_calls, [], [], 10, None,
                     "clean")
    assert row["tool_calls"][0]["name"] == "order.update"
    assert row["tool_calls"][0]["args"] == raw_calls[0]["args"]
    assert row["tool_calls"][0]["result"] == raw_calls[0]["result"]


def test_trace_masks_pii_in_query_without_aborting_run():
    raw_calls = [{"name": "catalog.search", "args": {"query": "0901234567"}}]
    row = trace_line("run", "full", "S01", "call_1", 1,
                     "Tìm sản phẩm", "Dạ", raw_calls, [], [], 10, None,
                     "clean")
    assert row["tool_calls"][0]["name"] == "catalog.search"
    assert row["tool_calls"][0]["args"]["query"] == "[SỐ ĐÃ ẨN]"


def test_trace_masks_contact_details_and_keeps_business_arguments():
    row = trace_line("run", "full", "S01", "call_1", 1,
                     "Số tôi 0901234567, địa chỉ: 12 đường Lê Lợi.",
                     "Tôi gọi 0901234567 sau ạ.",
                     [{"name": "order.create", "args": {
                         "sku": "SKU-A", "qty": 2, "customer_phone": "0901234567",
                         "address": "12 đường Lê Lợi"}}],
                     [{"key": "phone", "value": "0901234567"}], [], 123, None, "clean")
    encoded = json.dumps(row, ensure_ascii=False)
    assert "0901234567" not in encoded
    assert "12 đường Lê Lợi" not in encoded
    assert row["tool_calls"][0]["name"] == "order.create"
    assert row["tool_calls"][0]["args"]["sku"] == "SKU-A"
    assert row["tool_calls"][0]["args"]["qty"] == 2


def test_trace_masks_single_word_customer_name_across_text_tools_and_memory():
    row = trace_line("run", "full", "S01", "call_1", 1,
                     "Tôi tên Hoa.", "Chào chị Hoa.",
                     [{"name": "order.create", "args": {
                         "customer_name": "Hoa", "sku": "SKU-A"}}],
                     [{"key": "customer_name", "value": "Hoa",
                       "evidence_quote": "Hoa chọn SKU-A"}], [],
                     120, None, "clean", customer_name="Hoa")
    assert "Hoa" not in json.dumps(row, ensure_ascii=False)
    assert row["tool_calls"][0]["args"]["sku"] == "SKU-A"
