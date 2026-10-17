"""Catalog search keeps customer constraints while ranking descriptive words."""

import json
from pathlib import Path

from app.mcp_servers.mcp_shared.commerce_rules import _catalog


PRODUCTS = json.loads((Path(__file__).resolve().parents[3] /
                       "BTC-Data-Vong1-TEAMS/catalog/products.json").read_text())["products"]


def test_feature_words_do_not_exclude_matching_product_type():
    args = {"query": "máy lọc không khí khóa trẻ em",
            "max_price_vnd": 5_000_000, "min_room_area_m2": 25}
    result = _catalog(PRODUCTS, args)
    assert [item["sku"] for item in result["items"]] == ["SKU-AP-X", "SKU-XM-4L"]
    assert result["total"] == 2
    assert "SKU-AP-Y" not in [item["sku"] for item in result["items"]]


def test_unaccented_query_and_category_slug_match():
    result = _catalog(PRODUCTS, {"query": "may loc khong khi",
                                 "category": "gia-dung/may-loc-khong-khi",
                                 "max_price_vnd": 5_000_000,
                                 "min_room_area_m2": 25})
    assert [item["sku"] for item in result["items"]] == ["SKU-AP-X", "SKU-XM-4L"]
    assert _catalog(PRODUCTS, {"query": "may loc khong khi",
                               "category": "gia-dung/máy-lọc-không-khí",
                               "max_price_vnd": 5_000_000,
                               "min_room_area_m2": 25}) == result


def test_extra_words_score_zero_and_ties_keep_catalog_order():
    products = [
        {"sku": "A", "name": "Giày chạy bộ Alpha", "brand": "A",
         "category": "giay/chay-bo", "list_price_vnd": 100, "attributes": {}, "variants": []},
        {"sku": "B", "name": "Giày chạy bộ Beta", "brand": "B",
         "category": "giay/chay-bo", "list_price_vnd": 100, "attributes": {}, "variants": []},
        {"sku": "C", "name": "Áo khoác", "brand": "C",
         "category": "thoi-trang/ao", "list_price_vnd": 100, "attributes": {}, "variants": []},
        {"sku": "D", "name": "Giày chạy bộ chống nước", "brand": "D",
         "category": "giay/chay-bo", "list_price_vnd": 100, "attributes": {}, "variants": []},
    ]
    result = _catalog(products, {"query": "giày chạy bộ chống nước"})
    assert [item["sku"] for item in result["items"]] == ["D", "A", "B"]
    assert _catalog(products, {"query": "bàn phím"}) == {"items": [], "total": 0}


def test_other_category_respects_hard_price_and_type():
    result = _catalog(PRODUCTS, {"query": "giày chạy bộ nhẹ thoáng",
                                 "category": "thoi-trang/giay",
                                 "max_price_vnd": 2_000_000})
    assert result["items"]
    assert all(item["list_price_vnd"] <= 2_000_000 for item in result["items"])
    assert all(item["category"].startswith("thoi-trang/giay")
               for item in result["items"])
