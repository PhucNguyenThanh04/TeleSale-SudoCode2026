"""Trích entity từ transcript dạng viết: SKU theo catalog, tiền theo ngữ cảnh và các slot hội thoại."""
import unittest
from pathlib import Path

from speech.btc import find_data_dir, load_catalog, read_json
from speech.entities import build_catalog, extract_entities
from speech.evaluate import oracle_entities
from speech.normalize import normalize_text

BTC_DIR = find_data_dir(required=False)
TEAM_SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "team_dialogues.sample.json"

CATALOG = build_catalog([
    {"sku": "AIR-S", "name": "Máy lọc không khí Breezo S", "brand": "Breezo"},
    {"sku": "AIR-M", "name": "Máy lọc không khí Breezo M Pro", "brand": "Breezo"},
    {"sku": "AIR-FLT", "name": "Màng lọc Breezo S", "brand": "Breezo"},
    {"sku": "RUN-BLK", "name": "Giày chạy bộ Stride Lite đen", "brand": "Stride"},
    {"sku": "RUN-WHT", "name": "Giày chạy bộ Stride Lite trắng", "brand": "Stride"},
])


def entities(*turns: str) -> dict:
    return extract_entities(list(turns), CATALOG)[0]


class SkuTests(unittest.TestCase):
    def test_brand_and_model_pick_one_product(self):
        self.assertEqual(entities("chị lấy máy Breezo M Pro nhé")["sku"], "AIR-M")
        self.assertEqual(entities("máy Breezo S")["sku"], "AIR-S")

    def test_accessory_needs_an_accessory_word_before_the_brand(self):
        self.assertEqual(entities("thay màng lọc Breezo S")["sku"], "AIR-FLT")

    def test_brand_alone_or_tie_gives_no_sku(self):
        self.assertNotIn("sku", entities("bên em có Breezo nhé"))
        self.assertNotIn("sku", entities("đôi Stride Lite nha"))

    def test_model_without_brand_uses_brand_from_previous_turn(self):
        self.assertEqual(entities("Breezo S giá bao nhiêu em", "còn mẫu M Pro thì sao")["sku"], "AIR-M")


class MoneyTests(unittest.TestCase):
    def test_amount_kind_depends_on_context(self):
        cases = {"giá 3,49 triệu nha anh": ("price_vnd", 3490000),
                 "ngân sách của chị tầm 3 triệu thôi": ("budget_vnd", 3000000),
                 "chị mua tầm 2 triệu đổ lại": ("budget_vnd", 2000000),
                 "chỗ khác bán có 3 triệu 2 à": ("competitor_price_vnd", 3200000),
                 "đơn từ 500 nghìn được miễn phí vận chuyển": ("min_free_ship_vnd", 500000),
                 "phí ship 25 nghìn": ("shipping_fee_vnd", 25000),
                 "em giảm cho chị 200 nghìn": ("discount_vnd", 200000),
                 "giá 1.250.000đ": ("price_vnd", 1250000)}
        for text, (key, value) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(entities(text).get(key), value)

    def test_price_after_discount_is_a_price_not_a_discount(self):
        cases = {"giá sau khi giảm là 5 triệu": ("price_vnd", 5000000),
                 "sau khi giảm thì giá là 5,2 triệu": ("price_vnd", 5200000),
                 "áp voucher xong còn 3 triệu": ("price_vnd", 3000000),
                 "giảm còn 4 triệu 5": ("price_vnd", 4500000),
                 "được giảm giá 500 nghìn": ("discount_vnd", 500000),
                 "voucher giảm 200 nghìn": ("discount_vnd", 200000)}
        for text, (key, value) in cases.items():
            with self.subTest(text=text):
                found = entities(text)
                self.assertEqual(found.get(key), value)
                self.assertEqual(len([k for k in found if k.endswith("_vnd")]), 1)

    def test_counts_and_durations_are_not_money(self):
        self.assertEqual(entities("máy 9 lõi lọc, bảo hành 24 tháng"), {"warranty_months": 24})


class SlotTests(unittest.TestCase):
    def test_contact_order_and_policy_numbers(self):
        cases = {"số anh là 0912 345 678": ("phone", "0912345678"),
                 "số anh +84 912 345 678": ("phone", "0912345678"),
                 "mã đơn OD-77812 của anh": ("order_id", "OD77812"),
                 "bảo hành 2 năm": ("warranty_months", 24),
                 "đổi trả trong 15 ngày": ("return_days", 15),
                 "nội thành giao 1 đến 2 ngày là nhận": ("delivery_days", 2),
                 "chương trình tặng màng lọc đến hết 5/1": ("promo_expiry", "2027-01-05"),
                 "phòng khách 25 m2": ("room_area_m2", 25),
                 "phòng ngủ chừng 18 mét": ("room_area_m2", 18)}
        for text, (key, value) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(entities(text).get(key), value)

    def test_pickup_and_return_windows_are_not_delivery_time(self):
        self.assertNotIn("delivery_days", entities("shipper qua lấy hàng trong 2 ngày"))
        self.assertNotIn("delivery_days", entities("đổi trả trong 15 ngày"))

    def test_children_statement_but_not_question(self):
        self.assertIs(entities("nhà chị không có con nhỏ")["has_children"], False)
        self.assertIs(entities("nhà có bé 3 tuổi")["has_children"], True)
        self.assertNotIn("has_children", entities("nhà mình có bé nhỏ không chị"))

    def test_blockers(self):
        self.assertEqual(entities("để anh hỏi vợ đã")["blocker"], "can hoi vo")
        self.assertEqual(entities("bên kia bán rẻ hơn", "để anh cân nhắc thêm")["blocker"], "so sanh gia")

    def test_payment_choice_is_taken_only_from_statements(self):
        self.assertEqual(entities("anh chuyển khoản nhé")["payment"], "bank")
        self.assertEqual(entities("chị thanh toán khi nhận hàng nha")["payment"], "COD")
        self.assertNotIn("payment", entities("anh trả COD hay chuyển khoản"))
        self.assertNotIn("payment", entities("anh muốn trả COD không"))

    def test_read_back_counts_once_the_customer_confirms(self):
        read_back = "dạ em xác nhận lại giao về quận 3, thanh toán COD đúng không ạ?"
        self.assertEqual(entities(read_back, "đúng rồi em")["payment"], "COD")
        self.assertEqual(entities(read_back + " Dạ đúng rồi")["payment"], "COD")
        self.assertEqual(entities(read_back, "không em, anh chuyển khoản")["payment"], "bank")
        self.assertNotIn("payment", entities(read_back, "dạ em lên đơn luôn nhé"))
        self.assertNotIn("payment", entities(read_back, "đúng không nhỉ, để anh xem lại"))

    def test_size_change_across_turns(self):
        self.assertEqual(entities("đôi size 39 hơi rộng em", "đổi xuống size 38 giúp anh"),
                         {"size_old": 39, "size_new": 38})
        result = entities("áo size m chật quá, đổi lên l nhé")
        self.assertEqual((result["size_old"], result["size_new"]), ("M", "L"))

    def test_color_and_stock(self):
        self.assertEqual(entities("lấy màu xanh navy nha")["color"], "xanh navy")
        self.assertIs(entities("mẫu này đang tạm hết hàng ạ")["in_stock"], False)
        self.assertIs(entities("bên em không còn hàng")["in_stock"], False)
        self.assertIs(entities("hàng về rồi chị ạ")["in_stock"], True)
        self.assertIs(entities("dạ mẫu này có hàng lại rồi à, giá 5 triệu")["in_stock"], True)
        self.assertNotIn("in_stock", entities("size 38 còn hàng không em"))
        self.assertNotIn("in_stock", entities("vẫn còn hàng à?"))

    def test_free_exchange_fee(self):
        self.assertEqual(entities("đổi size lần đầu miễn phí ạ")["exchange_fee_vnd"], 0)


@unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
class BtcRegressionTests(unittest.TestCase):
    """Chỉ chống thoái lui: bộ trích được phát triển khi đã đọc các mẫu này, không phải ước lượng tổng quát."""

    def test_entities_from_correct_transcripts_match_labels(self):
        catalog = load_catalog(BTC_DIR)
        for path in (BTC_DIR / "asr" / "ground_truth.json", TEAM_SAMPLE):
            with self.subTest(path=path.name):
                self.assertEqual(oracle_entities(read_json(path), catalog)["oracle_entity_accuracy"], 100.0)

    def test_spoken_product_names_map_back_to_their_sku(self):
        # Giả lập ASR đúng tuyệt đối: tên catalog → dạng nói → dạng viết → SKU. Bỏ qua sản phẩm mà tên không chứa hãng
        # (vd "Bộ lõi lọc thay thế RO 1-2-3"): khách phải nói thêm hãng thì mới xác định được. HikePro đọc "hai pro"
        # trùng "2 Pro" (RunLite 2 Pro trong D04) nên chỉ nhận được khi ASR viết ra "HikePro"/"hike pro".
        ambiguous = {"SKU-SN-TRK"}
        catalog = load_catalog(BTC_DIR)
        for product in read_json(BTC_DIR / "catalog" / "products.json")["products"]:
            if product["brand"].lower() not in product["name"].lower() or product["sku"] in ambiguous:
                continue
            spoken = normalize_text(product["name"]).spoken
            with self.subTest(sku=product["sku"], spoken=spoken):
                merged, _ = extract_entities([normalize_text(spoken).written], catalog)
                self.assertIn(product["sku"], merged.get("sku") or [])


if __name__ == "__main__":
    unittest.main()
