"""Catalog search keeps customer constraints while ranking descriptive words."""

import asyncio
import json
from uuid import uuid4

from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.commerce_rules import _catalog
from app.schemas.agent import TextTurnRequest
from btc_data import btc_data_dir


PRODUCTS = json.loads((btc_data_dir() / "catalog/products.json").read_text(encoding="utf-8"))["products"]


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


def test_agent_catalog_boundary_returns_products_in_one_call_without_new_args():
    class Gateway:
        def __init__(self):
            self.calls = []

        async def invoke_trusted(self, name, args, *_):
            self.calls.append((name, args))
            return _catalog(PRODUCTS, args)

    gateway = Gateway()
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
                              channel="web_chat", channel_identity=None,
                              on="2026-10-15", input_mode="clean",
                              text="Tư vấn máy lọc không khí có khóa trẻ em cho phòng 25m2, giá tối đa 5 triệu.")
    state = {"request": request, "tool_calls": [], "tool_count": 0}
    business = BusinessTools(gateway, state, 3, lambda: None)
    search = next(tool for tool in business.langchain_tools()
                  if tool.name == "catalog.search")
    assert "required_features" not in search.args_schema.model_fields
    assert "unmatched_terms" not in search.args_schema.model_fields
    result = asyncio.run(business.invoke("catalog.search", {
        "query": "máy lọc không khí khóa trẻ em",
        "max_price_vnd": 5_000_000, "min_room_area_m2": 25,
    }))
    assert len(gateway.calls) == 1
    assert [item["sku"] for item in result["items"]] == ["SKU-AP-X", "SKU-XM-4L"]
    assert all(item["attributes"]["child_safe_lock"] is False
               for item in result["items"])
