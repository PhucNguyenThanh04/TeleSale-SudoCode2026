"""Kiểm kịch bản tự viết: định dạng, dạng nói, sự thật theo mock_tools BTC tại call_date."""
import copy
import unittest
import warnings

from speech.btc import find_data_dir, load_mock_tools
from speech.tts import with_full_text
from speech.validate import Reference, merge_turn_entities, validate

BTC_DIR = find_data_dir(required=False)
FAKE_PHONE = "0977000111"  # số giả, kiểm trong test là không trùng CRM


def dialogue(turns: list[tuple[str, str, dict]], **fields) -> dict:
    d = {"id": "X1", "split": "holdout", "noisy": False, "call_date": "2026-10-27",
         "agent_region": "bac", "agent_gender": "f", "customer_region": "nam", "customer_gender": "m",
         "turns": [{"idx": i, "speaker": s, "text": t, "entities": e} for i, (s, t, e) in enumerate(turns, start=1)]}
    d.update(fields)
    d["entities"] = merge_turn_entities(d["turns"])
    return d


GOOD = dialogue([
    ("A", "dạ em chào anh, anh đang quan tâm máy lọc không khí e pia y phải không ạ", {"sku": "SKU-AP-Y"}),
    ("C", "ừ, máy đó giá bao nhiêu em", {}),
    ("A", "dạ máy e pia y giá năm triệu hai trăm nghìn ạ", {"price_vnd": 5200000}),
    ("C", "còn hàng không em", {}),
    ("A", "dạ máy vẫn còn hàng, bảo hành hai mươi bốn tháng ạ", {"in_stock": True, "warranty_months": 24}),
    ("C", "ok, anh lấy, thanh toán khi nhận hàng nhé", {"payment": "COD"}),
    ("A", "dạ em lên đơn cho anh, giao trong hai đến ba ngày ạ", {"delivery_days": 3}),
])


def run(*dialogues, header=None):
    source = {"reference_date": "2026-10-15", "call_date_range": ["2026-10-15", "2026-10-31"],
              "tts_engine": "elevenlabs", **(header or {}), "dialogues": list(dialogues)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)  # mock_tools BTC mở file không đóng
        return validate([("x.json", source)], REF)


def messages(report, level="error"):
    return [i.message for i in report.issues if i.level == level]


REF = None


@unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
class ValidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global REF
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            REF = Reference.load(BTC_DIR)
        assert FAKE_PHONE not in REF.known_phones

    def edited(self, turn: int, text: str | None = None, entities: dict | None = None, **fields) -> dict:
        d = copy.deepcopy(GOOD)
        if text is not None:
            d["turns"][turn - 1]["text"] = text
        if entities is not None:
            d["turns"][turn - 1]["entities"] = entities
        d["entities"] = merge_turn_entities(d["turns"])
        d.update(fields)
        return d

    def test_clean_dialogue_has_no_error_and_reports_stats(self):
        report = run(GOOD)
        self.assertEqual(messages(report), [])
        stats = report.stats[0]
        self.assertEqual((stats.n_turns, stats.chars), (7, sum(len(t["text"]) for t in GOOD["turns"])))
        self.assertAlmostEqual(stats.credits, stats.chars * 0.5)
        self.assertGreater(stats.oracle[1], 0)

    def test_format_errors(self):
        d = self.edited(3, split="test", noisy="yes")
        d["turns"][3]["idx"] = 9
        d["turns"][1]["speaker"] = "B"
        errors = " | ".join(messages(run(d, copy.deepcopy(GOOD))))
        for needle in ("split", "noisy", "idx", "speaker", "id trùng"):
            self.assertIn(needle, errors)

    def test_spoken_form_rejects_digits_and_stray_placeholders(self):
        errors = " | ".join(messages(run(self.edited(2, "ừ, máy đó giá 5 triệu hả {kh}"))))
        self.assertIn("chữ số", errors)
        self.assertIn("{kh}", errors)

    def test_unknown_key_and_unmerged_dialogue_entities(self):
        d = self.edited(2, entities={"discount_vnd": 1})
        d["entities"] = {"sku": "SKU-AP-Y"}
        errors = " | ".join(messages(run(d)))
        self.assertIn("discount_vnd", errors)
        self.assertIn("gộp entity", errors)

    def test_label_must_be_spoken_in_its_turn(self):
        errors = messages(run(self.edited(3, "dạ máy này đang có giá tốt ạ")))
        self.assertTrue(any("không thấy được nói ra" in e for e in errors), errors)

    def test_price_must_match_mock_quote_on_call_date(self):
        wrong = self.edited(3, "dạ máy e pia y giá bốn triệu tám trăm chín mươi nghìn ạ", {"price_vnd": 4890000})
        self.assertTrue(any("không khớp SKU-AP-Y" in e for e in messages(run(wrong))))

    def test_stock_depends_on_call_date(self):
        d = dialogue([("A", "dạ máy e pia pro hiện vẫn còn hàng ạ", {"sku": "SKU-AP-PRO", "in_stock": True})],
                     call_date="2026-10-19")
        self.assertTrue(any("tồn kho SKU-AP-PRO" in e for e in messages(run(d))))
        d["call_date"] = "2026-10-22"
        self.assertFalse(any("tồn kho" in e for e in messages(run(d))))

    def test_holiday_is_error_and_sunday_is_warning(self):
        self.assertTrue(any("ngày nghỉ" in e for e in messages(run(self.edited(1, call_date="2026-10-26")))))
        self.assertTrue(any("Chủ nhật" in w for w in messages(run(self.edited(1, call_date="2026-10-25")), "warn")))

    def test_fake_pii_must_not_collide_with_crm(self):
        crm_phone = next(iter(sorted(REF.known_phones)))
        d = self.edited(6, f"ok, số anh là {self.spell(crm_phone)}", {"phone": crm_phone})
        self.assertTrue(any("trùng CRM" in e for e in messages(run(d))))
        d = self.edited(6, f"ok, số anh là {self.spell(FAKE_PHONE)}", {"phone": FAKE_PHONE})
        self.assertFalse(messages(run(d)))

    @staticmethod
    def spell(digits: str) -> str:
        names = "không một hai ba bốn năm sáu bảy tám chín".split()
        return " ".join(names[int(c)] for c in digits)

    def test_trade_in_price_needs_owned_sku_in_crm_overlay(self):
        d = self.edited(3, "dạ trừ thu cũ đổi mới thì máy e pia y còn bốn triệu tám trăm nghìn ạ",
                        {"price_vnd": 4800000})
        self.assertTrue(any("không khớp" in e for e in messages(run(d))))
        d["tool_context"] = {"customer_phone": FAKE_PHONE, "crm_overlay": [{
            "customer_id": "FAKE-1", "name": "khách giả lập", "honorific": "anh", "phone": FAKE_PHONE,
            "orders": [{"order_id": "OD990001", "sku": "SKU-AP-X-2024", "status": "delivered"}]}]}
        self.assertEqual(messages(run(d)), [])

    def test_explicit_checks_call_btc_tools(self):
        check = {"tool": "pricing.get_quote", "args": {"sku": "SKU-AF-6L"}, "turn": 2,
                 "not_applied": ["11-11"], "why": "agent nói KM 11/11 chưa áp dụng"}
        self.assertEqual(messages(run(self.edited(1, checks=[check]))), [])
        wrong = {**check, "not_applied": [], "applied": ["11-11"]}
        self.assertTrue(any("11-11" in e for e in messages(run(self.edited(1, checks=[wrong])))))
        eta = {"tool": "delivery.eta", "args": {"address": "Hà Nội"}, "expect": "2026-10-28", "why": "ngày giao"}
        self.assertEqual(messages(run(self.edited(1, call_date="2026-10-24", checks=[eta]))), [])

    def test_template_allows_kh_and_requires_distinct_team_voices(self):
        d = copy.deepcopy(GOOD)
        for field in ("agent_region", "agent_gender", "customer_region", "customer_gender"):
            d.pop(field)
        d.update(agent_voice="tv1", customer_voice="tv1")
        d["turns"][0]["text"] = "dạ em chào {kh}, {kh} đang quan tâm máy lọc không khí e pia y phải không ạ"
        errors = messages(run(d))
        self.assertEqual(errors, ["nhân viên và khách không được cùng một giọng"])
        d["customer_voice"] = "tv2"
        self.assertEqual(messages(run(d)), [])

    def test_output_ground_truth_drops_validator_only_fields(self):
        d = self.edited(1, tool_context={"address": "TP.HCM"}, checks=[{"tool": "inventory.check"}])
        out = with_full_text(d)
        self.assertNotIn("tool_context", out)
        self.assertNotIn("checks", out)
        self.assertEqual(out["n_turns"], 7)


@unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
class MockToolsLoaderTests(unittest.TestCase):
    def test_each_load_is_isolated_and_writes_no_bytecode(self):
        cache = BTC_DIR / "eval" / "__pycache__"
        before = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            first, second = load_mock_tools(BTC_DIR), load_mock_tools(BTC_DIR)
        first.order_create(FAKE_PHONE, "SKU-AP-Y", on="2026-10-27", address="Hà Nội")
        self.assertEqual(len(first._ORDERS), 1)
        self.assertEqual(len(second._ORDERS), 0)
        after = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else []
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
