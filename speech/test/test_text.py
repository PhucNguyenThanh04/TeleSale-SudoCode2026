"""Chuẩn hóa transcript Việt-Anh: đọc số, ITN, từ điển thuật ngữ và hai dạng spoken/written."""
import re
import unittest
from pathlib import Path

from speech.btc import find_data_dir, read_json
from speech.lexicon import build_lexicon, canonicalize, hotwords, load_lexicon, spoken_terms
from speech.normalize import normalize_text
from speech.textutil import btc_norm, tokenize
from speech.vi_numbers import itn, number_to_words, spell_numbers

BTC_DIR = find_data_dir(required=False)
TEAM_SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "team_dialogues.sample.json"


class NumberWordsTests(unittest.TestCase):
    def test_reads_numbers_in_ground_truth_style(self):
        cases = {0: "không", 15: "mười lăm", 21: "hai mươi mốt", 24: "hai mươi bốn", 105: "một trăm linh năm",
                 1005: "một nghìn không trăm linh năm", 690000: "sáu trăm chín mươi nghìn",
                 5200000: "năm triệu hai trăm nghìn"}
        for value, words in cases.items():
            with self.subTest(value=value):
                self.assertEqual(number_to_words(value), words)

    def test_zero_middle_group_is_not_read_as_a_bigger_amount(self):
        words = number_to_words(1000500)
        self.assertEqual(words, "một triệu không nghìn năm trăm")
        self.assertEqual(itn(words), "1000500")

    def test_spell_numbers_reads_phone_range_date_percent_and_money(self):
        cases = {"gọi 0938551246 nha": "gọi không chín ba tám năm năm một hai bốn sáu nha",
                 "giao 2-3 ngày": "giao hai đến ba ngày",
                 "lõi RO 1-2-3": "lõi RO một hai ba",
                 "số điện thoại không chín 3851246": "số điện thoại không chín ba tám năm một hai bốn sáu",
                 "mã đơn là OD487215": "mã đơn là OD bốn trăm tám mươi bảy nghìn hai trăm mười lăm",
                 "hẹn 27/10": "hẹn hai mươi bảy tháng mười",
                 "giảm 15%": "giảm mười lăm phần trăm"}
        for written, spoken in cases.items():
            with self.subTest(written=written):
                self.assertEqual(spell_numbers(written), spoken)

    def test_itn_writes_quantities_as_digits(self):
        cases = {"bốn triệu rưỡi": "4,5 triệu", "sáu trăm chín mươi nghìn": "690 nghìn",
                 "số không chín ba tám năm năm một hai bốn sáu": "số 0938551246", "máy chín lõi": "máy 9 lõi",
                 "bán có năm triệu bảy thôi": "bán có 5,7 triệu thôi", "bán có 5 triệu 7 thôi": "bán có 5,7 triệu thôi",
                 "giá 5 triệu 490 nghìn": "giá 5,49 triệu", "giá 5 triệu 200": "giá 5,2 triệu"}
        for spoken, written in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(itn(spoken), written)

    def test_itn_keeps_counting_words_inside_phrases(self):
        self.assertEqual(itn("đổi một máy"), "đổi một máy")


class LexiconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lexicon = load_lexicon()

    def test_vietnamese_spellings_of_english_terms_become_canonical(self):
        cases = {"anh chốt kê ô đê nhé": "anh chốt COD nhé",
                 "phí síp bao nhiêu": "phí ship bao nhiêu",
                 "máy lọc nước cà rô phi": "máy lọc nước Karofi",
                 "máy lọc rô": "máy lọc RO",
                 "mã đơn ô d ba trăm": "mã đơn OD ba trăm",
                 "đổi sai bốn mươi mốt": "đổi size bốn mươi mốt"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonicalize(raw, self.lexicon), expected)

    def test_ordinary_vietnamese_words_are_left_alone(self):
        for text in ("rủi ro cao", "con cá rô phi nướng", "anh nói sai hai lần", "ô đề tài này"):
            with self.subTest(text=text):
                self.assertEqual(canonicalize(text, self.lexicon), text)

    def test_spoken_form_of_acronym_is_case_sensitive(self):
        self.assertEqual(spoken_terms("công nghệ RO, rủi ro thấp", self.lexicon), "công nghệ rô, rủi ro thấp")

    def test_custom_entry_round_trips(self):
        lexicon = build_lexicon({"entries": [{"canonical": "Foo Max", "spoken": "phu mác", "variants": ["phu mác"]}]})
        self.assertEqual(canonicalize("mua phu mác", lexicon), "mua Foo Max")
        self.assertEqual(spoken_terms("mua Foo Max", lexicon), "mua phu mác")

    def test_hotwords_respect_limit(self):
        self.assertLessEqual(len(hotwords(self.lexicon, limit=5).split(", ")), 5)

    def test_catalog_model_words_and_loanwords_become_canonical(self):
        cases = {"máy hút sữa mê đê la xuynh mắc xi": "máy hút sữa Medela Swing Maxi",
                 "xe đẩy joie pắc nhé": "xe đẩy Joie Pact nhé",
                 "combi su gô can": "Combi Sugocal",
                 "máy samsung a ích bốn mươi": "máy Samsung AX bốn mươi",
                 "senko tê ét mười sáu": "Senko TS mười sáu",
                 "xiaomi smart bốn lai": "Xiaomi Smart bốn Lite",
                 "máy hâm sữa phát bốn chức năng": "máy hâm sữa Fatz bốn chức năng",
                 "giày trekking hike pro": "giày trekking HikePro",
                 "giày sờ ni cơ với giày trếch king": "giày sneaker với giày trekking",
                 "nhắn fan page hoặc ét em ét": "nhắn fanpage hoặc SMS",
                 "ghế có i sô phích không": "ghế có isofix không"}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonicalize(raw, self.lexicon), expected)

    def test_context_gated_model_words_leave_vietnamese_alone(self):
        for text in ("tương lai của con", "anh lai xe máy", "pắc kéo này", "sữa phát triển trí não",
                     "máy phát điện"):
            with self.subTest(text=text):
                self.assertEqual(canonicalize(text, self.lexicon), text)
        self.assertNotIn("HikePro", canonicalize("chị lấy hai pro nhé", self.lexicon))
        # Ground truth BTC D04: "giày run lai hai pro" là RunLite 2 Pro, nên "hai pro" không được tự thành HikePro.
        self.assertNotIn("HikePro", canonicalize("giày run lai hai pro", self.lexicon))

    @unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
    def test_every_latin_word_in_catalog_names_has_a_lexicon_entry(self):
        # Từ tiếng Việt viết không dấu và chữ cái đơn (BTC giữ "x", "y" trong ground truth) không cần mục riêng.
        allowed = {"cho", "phao", "thao", "thay", "xe"}
        known = {t.lower() for entry in self.lexicon.entries for t in tokenize(entry["canonical"])}
        missing = set()
        for product in read_json(BTC_DIR / "catalog" / "products.json")["products"]:
            for word in product["name"].split():
                low = word.lower()
                if re.fullmatch(r"[a-z]{2,}", low) and low not in known and low not in allowed:
                    missing.add(word)
        self.assertEqual(missing, set())


class NormalizeTests(unittest.TestCase):
    def assert_round_trip(self, sentence: str):
        """ASR nghe đúng từng chữ thì dạng nói không được đổi chữ nào (nếu không WER bị phạt oan)."""
        self.assertEqual(normalize_text(sentence).spoken, btc_norm(sentence))

    def test_written_form_uses_digits_and_canonical_names(self):
        result = normalize_text("dạ anh chốt kê ô đê đơn bốn triệu rưỡi nha")
        self.assertEqual(result.written, "dạ anh chốt COD đơn 4,5 triệu nha")
        self.assertEqual(result.spoken, "dạ anh chốt cê ô đê đơn bốn triệu rưỡi nha")

    def test_spoken_form_reads_digits_written_by_asr(self):
        self.assertEqual(normalize_text("giá 5.200.000đ, ship 2-3 ngày").spoken,
                         "giá năm triệu hai trăm nghìn đồng ship hai đến ba ngày")

    def test_correct_spoken_sentences_are_unchanged(self):
        for sentence in ("dạ em gửi anh mã đơn ô đê bốn trăm năm mươi mốt nghìn hai trăm ba mươi bốn",
                         "số của chị là không chín ba tám năm năm một hai bốn sáu",
                         "đổi size bốn mươi mốt miễn phí ship hai chiều",
                         "nội thành giao hai đến ba ngày chị nhé"):
            with self.subTest(sentence=sentence):
                self.assert_round_trip(sentence)

    @unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
    def test_every_btc_ground_truth_turn_round_trips(self):
        for dialogue in read_json(BTC_DIR / "asr" / "ground_truth.json")["dialogues"]:
            for turn in dialogue["turns"]:
                with self.subTest(dialogue=dialogue["id"], idx=turn.get("idx")):
                    self.assert_round_trip(turn["text"])

    def test_every_team_sample_turn_round_trips(self):
        for dialogue in read_json(TEAM_SAMPLE)["dialogues"]:
            for turn in dialogue["turns"]:
                with self.subTest(dialogue=dialogue["id"], idx=turn.get("idx")):
                    self.assert_round_trip(turn["text"])


if __name__ == "__main__":
    unittest.main()
