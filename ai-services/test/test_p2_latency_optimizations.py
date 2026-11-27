import asyncio
import time
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from app.agent.harness.authorization import authorize_write, deterministic_fast_authorize
from app.agent.implementations.business_agent import BusinessTools
from app.schemas.agent import TextTurnRequest


def _state(text: str, *, sku: str = "SKU-AP-X", price: int = 4890000) -> dict:
    req = TextTurnRequest(
        session_id=uuid4(),
        client_msg_id=uuid4(),
        channel="hotline",
        channel_identity="0900000001",
        input_mode="clean",
        text=text,
        on=date(2026, 10, 20),
    )
    return {
        "request": req,
        "safe_text": text,
        "identity_status": "known",
        "customer_id": "C001",
        "customer_phone": "0900000001",
        "history": [
            {
                "customer": "AirPure X giá bao nhiêu?",
                "agent": f"Máy lọc không khí AirPure X còn hàng, giá {price:,}đ ạ.".replace(",", "."),
            }
        ],
        "customer_statements": [],
        "profile": {},
        "scoped_facts": {"product": {}, "room": {}},
        "episodes": [],
        "current_episode": None,
        "call_brief": None,
        "tool_calls": [],
        "session_tool_calls": [
            {
                "name": "catalog.get_details",
                "args": {"sku": sku},
                "result": {"items": [{"sku": sku, "name": "Máy lọc không khí AirPure X", "variants": []}]},
            },
            {
                "name": "inventory.check",
                "args": {"sku": sku, "on": "2026-10-20"},
                "result": {"sku": sku, "in_stock": True, "qty": 10},
            },
            {
                "name": "pricing.get_quote",
                "args": {"sku": sku, "on": "2026-10-20", "customer_phone": "0900000001"},
                "result": {"sku": sku, "list_price_vnd": price, "final_price_vnd": price, "applied_promos": []},
            },
        ],
    }


def test_p2_fast_authorizer_approves_clear_order_without_llm_and_defers_ambiguous():
    args = {"sku": "SKU-AP-X", "qty": 1, "price_vnd": 4890000, "payment": "COD", "on": "2026-10-20", "customer_phone": "0900000001"}
    clear_state = _state("Ok em lên đơn cho anh 1 chiếc AirPure X, thanh toán COD nhé.")
    llm = AsyncMock()
    llm.with_structured_output.side_effect = AssertionError("Fast path should not invoke LLM")
    allowed = asyncio.run(authorize_write(llm, clear_state, "order.create", args, 6))
    assert allowed is True

    for ambiguous_text in (
        "Nếu anh lên đơn thì giao mấy ngày?",
        "Anh chưa lên đơn đâu, chỉ hỏi trước thôi.",
        "Vợ anh đồng ý rồi nhưng để anh cân nhắc thêm.",
        "Ok em lên đơn cho anh nhưng giá 3.000.000đ nhé.",
    ):
        st = _state(ambiguous_text)
        assert deterministic_fast_authorize("order.create", args, st) is None


def test_p2_parallel_read_tools_execute_concurrently():
    async def slow_invoke(name, args, *_a, **_kw):
        await asyncio.sleep(0.15)
        if name == "inventory.check":
            return {"sku": args["sku"], "in_stock": True, "qty": 5}
        if name == "pricing.get_quote":
            return {"sku": args["sku"], "list_price_vnd": 4890000, "final_price_vnd": 4890000, "applied_promos": []}
        return {"items": [{"sku": args["sku"], "name": "AirPure X", "variants": []}]}

    gateway = AsyncMock()
    gateway.invoke_trusted.side_effect = slow_invoke
    st = _state("Kiểm tra giá và tồn kho AirPure X")
    st["tool_calls"] = []
    business = BusinessTools(gateway, st, 8, lambda: datetime.now(timezone.utc))

    async def run():
        t0 = time.perf_counter()
        r1, r2, r3 = await asyncio.gather(
            business.invoke("catalog.get_details", {"sku": "SKU-AP-X"}),
            business.invoke("inventory.check", {"sku": "SKU-AP-X"}),
            business.invoke("pricing.get_quote", {"sku": "SKU-AP-X"}),
        )
        elapsed = time.perf_counter() - t0
        assert "error" not in r1 and "error" not in r2 and "error" not in r3
        assert elapsed < 0.32, f"Read tools ran serially ({elapsed:.3f}s)"

    asyncio.run(run())


def _catalog_gateway(items):
    async def invoke(name, args, *_a, **_kw):
        if name == "catalog.search":
            return {"items": items}
        if name == "inventory.check":
            return {"sku": args["sku"], "in_stock": True, "qty": 5}
        if name == "pricing.get_quote":
            return {"sku": args["sku"], "list_price_vnd": 4890000, "final_price_vnd": 4590000, "applied_promos": []}
        raise AssertionError(name)
    gateway = AsyncMock()
    gateway.invoke_trusted.side_effect = invoke
    return gateway


def test_single_catalog_hit_carries_current_quote_and_stock():
    item = {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X", "list_price_vnd": 4890000, "variants": []}
    gateway = _catalog_gateway([item])
    st = _state("AirPure X giá bao nhiêu, còn hàng không?")
    st["tool_calls"], st["session_tool_calls"] = [], []
    result = asyncio.run(BusinessTools(gateway, st, 8, lambda: datetime.now(timezone.utc)).invoke(
        "catalog.search", {"query": "AirPure X"}))
    assert result["current_quote"]["final_price_vnd"] == 4590000
    assert result["current_stock"]["in_stock"] is True
    assert sorted(call["name"] for call in st["tool_calls"]) == ["catalog.search", "inventory.check", "pricing.get_quote"]


def test_ambiguous_or_variant_catalog_hits_are_not_prefetched():
    variant = {"sku": "SKU-SN-RUN2", "name": "Giày RunLite 2 Pro",
               "variants": [{"variant_sku": "SKU-SN-RUN2-40-DEN", "size": "40"}]}
    other = {"sku": "SKU-AP-Y", "name": "Máy lọc không khí AirPure Y", "variants": []}
    plain = {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X", "variants": []}
    for items in ([variant], [plain, other]):
        st = _state("Cho anh xem mẫu này")
        st["tool_calls"], st["session_tool_calls"] = [], []
        result = asyncio.run(BusinessTools(_catalog_gateway(items), st, 8, lambda: datetime.now(timezone.utc)).invoke(
            "catalog.search", {"query": "mẫu"}))
        assert "current_quote" not in result and "current_stock" not in result
        assert [call["name"] for call in st["tool_calls"]] == ["catalog.search"]
