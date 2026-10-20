"""Validate the independent multi-session memory contract fixture."""

import unittest
from pathlib import Path
from datetime import date
import json
import os
import re


FIXTURE = Path(__file__).parent / "fixtures" / "memory_contract_v1.json"
REQUIRED = {"correction", "shared_phone", "cross_channel", "many_products",
            "return_after_months", "erase_request"}


class MemoryContractFixtureTest(unittest.TestCase):
    def test_six_cases_have_turn_expectations_and_controls(self):
        from memory_contract import load_cases

        cases = load_cases(FIXTURE)
        self.assertEqual({case["case"] for case in cases}, REQUIRED)
        for case in cases:
            with self.subTest(case=case["case"]):
                self.assertTrue(case["variant"])
                self.assertTrue(case["control"])
                self.assertTrue(case["calls"])
                for call in case["calls"]:
                    self.assertRegex(call["on"], r"^202[6-9]-\d\d-\d\d$")
                    date.fromisoformat(call["on"])
                    self.assertIn(call["channel"], {"hotline", "chat_fanpage", "zalo_oa"})
                    for turn in call["turns"]:
                        self.assertTrue(turn["text"])
                        self.assertIn("expected_after_turn", turn)
                        self.assertIn("forbidden", turn)
        long_case = next(case for case in cases if case["case"] == "many_products")
        self.assertGreaterEqual(sum(len(call["turns"]) for call in long_case["calls"]), 16)

    def test_four_product_skus_are_real_and_outside_public_samples(self):
        from memory_contract import load_cases

        cases = {case["case"]: case for case in load_cases(FIXTURE)}
        mentioned = set(re.findall(r"SKU-[A-Z0-9-]+", cases["many_products"]["variant"]))
        btc_dir = Path(os.getenv("BTC_DATA_DIR", FIXTURE.parents[4] /
                                  "BTC-Data-Vong1-TEAMS"))
        catalog = json.loads((btc_dir / "catalog" / "products.json").read_text())
        valid = {product["sku"] for product in catalog["products"]}
        samples = " ".join(path.read_text() for path in
                           (btc_dir / "test_set" / "public_sample").glob("*.json"))
        self.assertEqual(len(mentioned), 4)
        self.assertLessEqual(mentioned, valid)
        self.assertTrue(all(sku not in samples for sku in mentioned))

    def test_snapshot_check_is_subset_based_and_reports_fields_only(self):
        from memory_contract import check_snapshot

        actual = {"profile": {"budget_vnd": {"value": 4_000_000}},
                  "agent_text": "Dạ, em thấy số 0912345678.", "unused": "allowed"}
        self.assertEqual(check_snapshot({"profile": {"budget_vnd": {"value": 4_000_000}}},
                                        actual), [])
        errors = check_snapshot({"profile": {"budget_vnd": {"value": 5_000_000}},
                                 "agent_text": {"not_contains": "0912345678"}}, actual)
        self.assertTrue(any("profile.budget_vnd.value" in error for error in errors))
        self.assertTrue(any("agent_text" in error for error in errors))
        self.assertFalse(any("0912345678" in error for error in errors))

    def test_snapshot_can_find_a_tool_call_among_other_calls(self):
        from memory_contract import check_snapshot

        actual = {"tool_calls": [{"name": "crm.get_customer", "args": {}},
                                 {"name": "pricing.get_quote",
                                  "args": {"sku": "SKU-AP-MINI", "on": "2026-10-15"}}]}
        self.assertEqual(check_snapshot({"tool_calls": {"contains": {
            "name": "pricing.get_quote", "args": {"sku": "SKU-AP-MINI"}}}}, actual), [])
        self.assertTrue(check_snapshot({"tool_calls": {"not_contains": "order.create"}},
                                       {"tool_calls": [{"name": "order.create"}]}))

    def test_snapshot_rejects_disallowed_prior_fact_value(self):
        from memory_contract import check_snapshot

        constraint = {"profile": {"preferred_color": {"value": {"not_equals": "đen"}}}}
        self.assertEqual(check_snapshot(constraint, {"profile": {
            "preferred_color": {"value": "trắng"}}}), [])
        self.assertTrue(check_snapshot(constraint, {"profile": {
            "preferred_color": {"value": "đen"}}}))

    def test_forbidden_content_nested_in_tool_args_is_detected(self):
        from memory_contract import check_snapshot

        expected = {"tool_calls": {"not_contains": "0912345678"}}
        actual = {"tool_calls": [{"name": "order.create",
                                  "args": {"address": {"note": "gọi 0912345678"}}}]}
        self.assertTrue(check_snapshot(expected, actual))

    def test_active_room_projection_requires_separate_scope(self):
        from contract_memory_updates import active_room_constraints

        legacy = {"room_area_m2": {"value": 45},
                  "note": "Trước đây khách nói phòng nhỏ 12 m²"}
        self.assertEqual(active_room_constraints(legacy), [])
        scoped = {"rooms": [
            {"room": "phòng nhỏ", "room_area_m2": 12, "status": "active"},
            {"room": "phòng thứ hai", "room_area_m2": 45, "status": "active"},
            {"room": "phòng cũ", "room_area_m2": 60, "status": "superseded"},
        ]}
        self.assertEqual(active_room_constraints(scoped),
                         [("phòng nhỏ", 12), ("phòng thứ hai", 45)])
