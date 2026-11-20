
import json
import unittest
from datetime import date
from uuid import uuid4

from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_shared.commerce_rules import _catalog
from app.schemas.agent import TextTurnRequest
from btc_data import btc_data_dir


PRODUCTS = btc_data_dir() / "catalog/products.json"


def state(query, **args):
    return {
        "request": TextTurnRequest(
            client_msg_id=uuid4(), session_id=uuid4(), channel="zalo_oa",
            channel_identity="test", on=date(2026, 10, 15),
            text="Tư vấn sản phẩm", input_mode="clean"),
        "decision": Decision(action="tool", tool_name="catalog.search",
                             tool_args={"query": query, **args}),
        "tool_calls": [],
    }


class CatalogQueryTest(unittest.TestCase):

    def test_widened_search_keeps_previous_filters(self):
        current = state("máy lọc không khí")
        current["tool_calls"] = [{
            "name": "catalog.search",
            "args": {"query": "máy lọc không khí cho phòng ngủ",
                     "min_room_area_m2": 25, "max_price_vnd": 5500000},
            "result": {"items": [], "total": 0},
        }]
        self.assertEqual(prepare_tool_call(current, lambda: None),
                         ("catalog.search", {"query": "máy lọc không khí",
                                             "min_room_area_m2": 25,
                                             "max_price_vnd": 5500000}))

    def test_new_search_does_not_inherit_old_filters(self):
        current = state("giày chạy bộ")
        current["tool_calls"] = [{
            "name": "catalog.search",
            "args": {"query": "máy lọc không khí", "min_room_area_m2": 25},
            "result": {"items": [], "total": 0},
        }]
        self.assertEqual(prepare_tool_call(current, lambda: None),
                         ("catalog.search", {"query": "giày chạy bộ"}))


if __name__ == "__main__":
    unittest.main()
