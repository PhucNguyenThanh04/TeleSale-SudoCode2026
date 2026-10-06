"""A completed turn must be available to the next turn in the same session."""

import asyncio
import json
from uuid import uuid4

import pytest

from app.agent.runtime import HarnessRuntime
from fake_memory import InMemoryStore
from test_graph import FakeModel, FakeTools, turn


async def _follow_up_reads_persisted_turn_across_runtime_instances():
    memory = InMemoryStore()
    tools = FakeTools({
        "crm.get_customer": {"found": False},
        "catalog.search": {"items": [{"sku": "SKU-AP-X", "name": "AirPure X"}],
                           "total": 1},
        "pricing.get_quote": {"sku": "SKU-AP-X", "list_price_vnd": 4890000,
                              "final_price_vnd": 4890000, "applied_promos": [],
                              "freeship": False},
    })
    first_model = FakeModel(
        {"action": "tool", "tool_name": "catalog.search",
         "tool_args": {"query": "AirPure X"}},
        {"action": "respond", "response": "Dạ, em thấy mẫu AirPure X ạ."},
    )
    first_turn = turn(text="Cho xem máy lọc AirPure X")
    first = await HarnessRuntime(first_model, tools, memory).run(first_turn)
    assert first.agent_text == "Dạ, em thấy mẫu AirPure X ạ."

    second_model = FakeModel(
        {"action": "tool", "tool_name": "pricing.get_quote",
         "tool_args": {"sku": "SKU-AP-X"}},
        {"action": "respond", "response": "Dạ, AirPure X có giá 4.890.000đ ạ."},
    )
    second_turn = turn(client_msg_id=uuid4(), text="Giá bao nhiêu ạ?")
    second = await HarnessRuntime(second_model, tools, memory).run(second_turn)
    context = json.loads(second_model.seen[0][1].content)
    assert context["session_history"] == [{
        "customer": "Cho xem máy lọc AirPure X",
        "agent": first.agent_text,
    }]
    assert second.agent_text == "Dạ, AirPure X có giá 4.890.000đ ạ."
    assert [row["customer"] for row in memory.sessions[str(first_turn.session_id)]] == [
        first_turn.text, second_turn.text,
    ]
    assert [args["sku"] for name, args in tools.calls if name == "pricing.get_quote"] == [
        "SKU-AP-X",
    ]


def test_follow_up_reads_persisted_turn_across_runtime_instances():
    asyncio.run(_follow_up_reads_persisted_turn_across_runtime_instances())


async def _variant_quote_follow_up_does_not_quote_parent_sku():
    memory = InMemoryStore()
    catalog = {"sku": "SKU-SN-CAS", "name": "Giày sneaker Urban Classic",
               "variants": [{"variant_sku": "SKU-SN-CAS-39-DEN", "size": 39,
                             "color": "den", "price_delta_vnd": 0}]}
    tools = FakeTools({
        "crm.get_customer": {"found": False},
        "catalog.search": {"items": [catalog], "total": 1},
        "inventory.check": {"sku": "SKU-SN-CAS-39-DEN", "in_stock": True, "qty": 9},
        ("pricing.get_quote", "SKU-SN-CAS-39-DEN"):
            {"sku": "SKU-SN-CAS-39-DEN", "list_price_vnd": 890000,
             "final_price_vnd": 890000,
             "applied_promos": [{"promo_code": "COD-0", "type": "freecod",
                                 "discount_vnd": 0}], "freeship": False},
    })
    first_model = FakeModel(
        {"action": "tool", "tool_name": "catalog.search",
         "tool_args": {"query": "Giày sneaker Urban Classic"}},
        {"action": "tool", "tool_name": "inventory.check",
         "tool_args": {"sku": "SKU-SN-CAS-39-DEN"}},
        {"action": "respond",
         "response": "Dạ, Giày sneaker Urban Classic size 39 màu đen hiện vẫn còn hàng ạ."},
    )
    await HarnessRuntime(first_model, tools, memory).run(
        turn(text="Giày sneaker Urban Classic size 39 màu đen còn hàng không?"))

    second_model = FakeModel(
        {"action": "tool", "tool_name": "catalog.search",
         "tool_args": {"query": "Giày sneaker Urban Classic"}},
        {"action": "tool", "tool_name": "pricing.get_quote",
         "tool_args": {"sku": "SKU-SN-CAS-39-DEN"}},
        {"action": "respond",
         "response": "Dạ, mẫu này có giá là 890.000đ và hiện chưa có chương trình giảm giá thêm ạ."},
    )
    answer = await HarnessRuntime(second_model, tools, memory).run(
        turn(client_msg_id=uuid4(), text="Giá mẫu này sao em?"))
    assert answer.agent_text == (
        "Dạ, mẫu này có giá là 890.000đ và hiện chưa có chương trình giảm giá thêm ạ.")
    assert [args["sku"] for name, args in tools.calls if name == "pricing.get_quote"] == [
        "SKU-SN-CAS-39-DEN",
    ]
    assert len(second_model.seen) == 3


def test_variant_quote_follow_up_does_not_quote_parent_sku():
    asyncio.run(_variant_quote_follow_up_does_not_quote_parent_sku())


async def _other_session_cannot_see_previous_session_history():
    memory = InMemoryStore()
    tools = FakeTools({"crm.get_customer": {"found": False}})
    await HarnessRuntime(FakeModel({"action": "respond", "response": "Dạ, em hỗ trợ ạ."}),
                         tools, memory).run(turn(text="Tôi xem AirPure X"))
    model = FakeModel({"action": "respond", "response": "Dạ, em hỗ trợ ạ."})
    await HarnessRuntime(model, tools, memory).run(
        turn(session=str(uuid4()), client_msg_id=uuid4(), text="Giá bao nhiêu?"))
    assert json.loads(model.seen[0][1].content)["session_history"] == []


def test_other_session_cannot_see_previous_session_history():
    asyncio.run(_other_session_cannot_see_previous_session_history())


async def _failed_turn_write_does_not_return_success(failure):
    class FailingMemory(InMemoryStore):
        async def record_turn(self, *_args, **_kwargs):
            if failure == "exception":
                raise ConnectionError("memory unavailable")
            if failure == "error":
                return {"error": "tool_unavailable"}
            return {"turn_no": 0}

    runtime = HarnessRuntime(FakeModel({"action": "respond", "response": "Dạ, em hỗ trợ ạ."}),
                             FakeTools({"crm.get_customer": {"found": False}}),
                             FailingMemory())
    request = turn(text="Chào shop")
    with pytest.raises(RuntimeError, match="memory_turn_write_failed"):
        await runtime.run(request)
    assert runtime.state_for(request) is None


@pytest.mark.parametrize("failure", ["exception", "error", "invalid"])
def test_failed_turn_write_does_not_return_success(failure):
    asyncio.run(_failed_turn_write_does_not_return_success(failure))


async def _repeated_message_id_returns_cached_response_without_second_write():
    memory = InMemoryStore()
    runtime = HarnessRuntime(FakeModel({"action": "respond", "response": "Dạ, em hỗ trợ ạ."}),
                             FakeTools({"crm.get_customer": {"found": False}}), memory)
    request = turn(text="Chào shop")
    first = await runtime.run(request)
    assert await runtime.run(request) == first
    assert len(memory.sessions[str(request.session_id)]) == 1


def test_repeated_message_id_returns_cached_response_without_second_write():
    asyncio.run(_repeated_message_id_returns_cached_response_without_second_write())
