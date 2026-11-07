"""Acceptance and context nodes shared by the production one-turn graph."""

import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.harness.context import load_context
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.agent.guardrails.checks import mask_pii
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway


def _mentions_children(text: str) -> bool:
    folded = text.casefold().replace("đ", "d")
    folded = "".join(char for char in unicodedata.normalize("NFD", folded)
                     if unicodedata.category(char) != "Mn")
    return bool(re.search(r"\b(?:con|be|tre nho|em be)\b", folded))


def safe_catalog_reply(state: TurnState) -> str | None:
    """Render the same sourced shortlist used for bounded quote preparation."""
    from app.mcp_servers.mcp_shared.consultation_shortlist import (
        build_shortlist, consultation_active, consultation_scope, shortlist_requirements, prefers_child_safety,
    )
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    if not consultation_active(state):
        return None
    scope = consultation_scope(state)
    shortlist = build_shortlist(state, scope=scope, quoted_only=True)
    if not shortlist.scope_known:
        from app.agent.guardrails.checks import _money_claims
        if 'consultation_scope' not in state or _money_claims(state.get('agent_draft', '')):
            return None
        return 'Mình đang muốn được tư vấn loại sản phẩm nào để em kiểm tra đúng nhu cầu ạ?'
    if 'budget_basis' in shortlist.missing_fields:
        return 'Mức ngân sách mình nêu là cho mỗi sản phẩm hay tổng cả đơn ạ?'
    if not shortlist.items:
        pending = build_shortlist(state, scope=scope)
        if not pending.items:
            if any(k in pending.missing_fields for k in ('size', 'color', 'variant')):
                return 'Mình cho em biết size hoặc màu cần chọn để em kiểm tra đúng phiên bản ạ?'
            return 'Em chưa xác minh được phương án đáp ứng các yêu cầu mình đã nêu. Mình muốn làm rõ yêu cầu nào trước ạ?'
        names = ', '.join(item['name'] for item in pending.items[:2] if item.get('name'))
        return mask_pii(f'Dạ, em tìm thấy {names}. Em chưa xác minh được giá cuối cho các phương án này để so sánh với mức chi của mình ạ.')
    item = shortlist.items[0]
    price = item['quoted_price_vnd']
    budget = derive_consultation(state).snapshot.budget
    qty = item['quote_qty']
    amount = price * (qty if budget.basis == 'total' else 1)
    answer = f"Dạ, em đề xuất {item['name']} có giá cuối {price:,}đ theo ngày cuộc gọi".replace(',', '.')
    needs = shortlist_requirements(state)
    area = needs.get('room_area_m2')
    attrs = item.get('attributes') or {}
    if type(area) in (int, float) and type(attrs.get('room_area_m2')) in (int, float) and attrs['room_area_m2'] >= area:
        answer += f', đáp ứng phòng {area:g} m²'
    answer += '.'
    soft_child = prefers_child_safety(state)
    lock = attrs.get('child_safe_lock')
    if soft_child and type(lock) is bool:
        answer += f" {item['name']} {'có' if lock else 'không có'} khóa trẻ em."
    if budget.limit_vnd is not None and amount > budget.limit_vnd and budget.mode == 'hard':
        return mask_pii(f"Dạ, em tìm thấy {item['name']}, nhưng các phương án đã kiểm tra chưa đáp ứng mức chi tối đa. Mình muốn em tìm thêm phương án trong mức chi này không ạ?")
    if budget.limit_vnd is not None and amount > budget.limit_vnd:
        answer += ' Phương án này vượt mức chi mình đã nêu. Mình có đồng ý điều chỉnh mức chi này không ạ?'
    elif soft_child and lock is not True:
        answer += ' Khóa trẻ em có phải yêu cầu bắt buộc của mình không ạ?'
    else:
        answer += ' Mình muốn em kiểm tra tồn kho phương án này không ạ?'
    return mask_pii(answer)


def safe_promotion_reply(state: TurnState) -> str | None:
    """Describe only promotions applied by a current-turn quote for one SKU."""
    if not re.search(r"(?i)\b(?:khuyến mãi|ưu đãi|giảm|tặng|quà|ship|cod)\b",
                     state.get("safe_text", "")):
        return None
    calls = build_commerce_evidence(state)
    quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
              and isinstance(call.get("result"), dict)
              and "error" not in call["result"]
              and isinstance(call.get("args", {}).get("sku"), str)
              and call["result"].get("sku") == call["args"]["sku"]]
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    from app.agent.harness.policy import resolve_product_selection
    focus = derive_consultation(state).focus_sku
    selection = resolve_product_selection(state, {'sku': focus}) if focus else None
    allowed = {focus, selection.sku if selection and selection.status == 'resolved' else None}
    if focus:
        quotes = [call for call in quotes if call['args']['sku'] in allowed]
    if len({call["args"]["sku"] for call in quotes}) != 1:
        return None
    quote = quotes[-1]["result"]
    sku = quotes[-1]["args"]["sku"]
    items = [item for call in calls if call.get("name") == "catalog.search"
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and isinstance(item.get("sku"), str)
             and isinstance(item.get("name"), str)]
    product = next((item for item in reversed(items) if item["sku"] in {sku, focus}), None)
    if not product:
        return None
    names = {item["sku"]: item["name"] for item in items}
    offers = []
    for promo in quote.get("applied_promos", []):
        if not isinstance(promo, dict):
            continue
        gift = promo.get("gift_sku")
        discount = promo.get("discount_vnd")
        if promo.get("type") == "gift" and isinstance(gift, str):
            if gift in names:
                offers.append(f"tặng {promo.get('qty', 1)} {names[gift]}")
            elif isinstance(promo.get("promo_code"), str):
                offers.append(f"tặng quà kèm theo chương trình {promo['promo_code']}")
        elif type(discount) is int and discount > 0:
            amount = f"{discount:,}".replace(",", ".")
            offers.append(f"giảm {amount}đ")
    if quote.get('freeship') is True:
        offers.append('miễn phí vận chuyển')
    if any(p.get('type')=='freecod' for p in quote.get('applied_promos',[]) if isinstance(p,dict)):
        offers.append('miễn phí thu hộ COD')
    if not offers:
        return None
    return mask_pii(
        f"Dạ, khuyến mãi đang áp dụng cho {product['name']} theo ngày cuộc gọi là "
        + ", ".join(offers) + " ạ."
    )


def transaction_selection_mismatch(state: TurnState) -> bool:
    from app.agent.harness.policy import resolve_product_selection
    for call in state.get("tool_calls", []):
        if call.get("name") == "order.create" and call.get("result", {}).get("status") == "created":
            selection = resolve_product_selection(state, call.get("args", {}))
            if selection.status != "catalog_required" and selection.sku != call.get("args", {}).get("sku"):
                return True
    return False


def safe_transaction_reply(state: TurnState) -> str | None:
    """Describe a completed write without causing another side effect."""
    writes = [c for c in state.get("tool_calls", []) if c.get("name") == "order.create"]
    if not writes:
        return None
    uncertain = "Dạ, trạng thái đơn hàng cần được kiểm tra lại trước khi xác nhận ạ."
    if len(writes) != 1:
        return uncertain
    call = writes[0]
    result = call.get("result", {})
    if result.get("status") != "created" or not isinstance(result.get("order_id"), str):
        if result.get("error") in {"out_of_stock", "price_mismatch", "variant_selection_required",
                                   "invalid_payment", "invalid_qty", "cod_limit_exceeded"}:
            return "Dạ, yêu cầu tạo đơn chưa thành công. Mình cần kiểm tra lại điều kiện đặt hàng ạ."
        return uncertain
    if transaction_selection_mismatch(state):
        return uncertain
    answer = f"Dạ, em đã tạo đơn {result['order_id']} cho mình."
    # Omit price here: a successful order alone does not supply a current quote
    # in every transport. The identifier is enough to acknowledge the transaction.
    return mask_pii(answer)


def safe_quote_reply(state: TurnState) -> str | None:
    if any(c.get("name") == "order.create" for c in state.get("tool_calls", [])):
        return None
    request = state.get("request")
    if request is None:
        return None
    on = request.on.isoformat()
    quotes = [c for c in build_commerce_evidence(state) if c.get("name") == "pricing.get_quote"
              and "error" not in c.get("result", {}) and c.get("args", {}).get("on") == on]
    if not quotes:
        return None
    from app.mcp_servers.mcp_shared.consultation import derive_consultation, requested_quantity
    decision=derive_consultation(state)
    focus=decision.focus_sku
    attempted={c.get('args',{}).get('sku') for c in
               [*state.get('session_tool_calls',[]),*state.get('tool_calls',[])]
               if c.get('name')=='pricing.get_quote'}-{None}
    if not focus and len(attempted)>1:
        return None
    qty=requested_quantity(state) or (decision.snapshot.accepted_offer.qty if decision.snapshot.accepted_offer else 1)
    from app.agent.harness.policy import resolve_product_selection
    selected=resolve_product_selection(state,{'sku':focus}) if focus else None
    allowed={focus,selected.sku if selected and selected.status=='resolved' else None}
    quotes=[c for c in quotes if (not focus or c.get('args',{}).get('sku') in allowed) and c.get('args',{}).get('qty',1)==qty]
    if not quotes or len({c["args"]["sku"] for c in quotes}) != 1:return None
    quote = quotes[-1]
    sku, result = quote["args"].get("sku"), quote["result"]
    price = result.get("final_price_vnd")
    if not isinstance(sku, str) or result.get("sku") != sku or type(price) is not int:
        return None
    from app.mcp_servers.mcp_shared.consultation import catalog_items,purchase_block_reason
    items=catalog_items(state)
    label=items.get(focus,items.get(sku,{})).get('name',sku)
    answer=f"Dạ, giá hiện tại của {label} là {price:,}đ ạ.".replace(',', '.')
    d=derive_consultation(state)
    if d.purchase_intent and purchase_block_reason(state,{'sku':sku,'qty':qty,'price_vnd':price}) in {'offer_confirmation_required','budget_consent_required'}:
        from app.mcp_servers.mcp_shared.consultation import worse_terms, quote_terms
        old=d.snapshot.accepted_offer
        if old and price>old.price_vnd:
            answer += " Giá hiện tại cao hơn mức mình đã đồng ý trước đó."
        elif old and worse_terms(old.promo_terms,quote_terms(result)):
            answer += " Quyền lợi hiện tại không còn như báo giá mình đã đồng ý trước đó."
        answer += " Báo giá cần được xác nhận lại trước khi tạo đơn. Mình đồng ý báo giá này để em lên đơn không ạ?"
    return mask_pii(answer)


def safe_consultation_reply(state: TurnState) -> str | None:
    """Pure task-aware recovery; transaction writes remain in orchestration."""
    from app.mcp_servers.mcp_shared.consultation import (
        derive_consultation, consultation_missing_fields, current_quote, requested_quantity, _search_text)
    decision = derive_consultation(state)
    if decision.next_action == 'pause':
        return 'Dạ, em ghi nhận mình chưa mua lúc này. Khi cần mình liên hệ lại nhé.'
    if decision.purchase_intent:
        missing = consultation_missing_fields(state)
        if not missing:
            return None  # Orchestration must complete the purchase, never pretend here.
        if 'selection' in missing:
            return 'Mình muốn lấy mẫu nào trong các mẫu đang trao đổi để em kiểm tra và lên đơn ạ?'
        if any(field in missing for field in ('size', 'color')):
            fields = [label for key, label in (('size','size'),('color','màu')) if key in missing]
            return 'Mình muốn lấy ' + ' và '.join(fields) + ' nào để em kiểm tra đúng phiên bản ạ?'
        if 'payment' in missing:
            return 'Mình muốn thanh toán bằng phương thức nào ạ?'
        if 'budget_basis' in missing:
            return 'Mức ngân sách mình nêu là cho mỗi sản phẩm hay tổng cả đơn ạ?'
        if any(field in missing for field in ('offer','budget')):
            answer = safe_quote_reply(state)
            if answer:
                return answer
        if 'identity' in missing:
            return 'Mình vui lòng xác minh thông tin khách hàng để em tiếp tục đặt hàng ạ.'
        if 'delivery' in missing:
            return ('Em chưa xác minh được khả năng đáp ứng thời hạn mình yêu cầu. '
                    'Mình có muốn em kiểm tra thêm khả năng đáp ứng thời hạn này không ạ?')
        if 'requirements' in missing:
            return 'Mẫu đang chọn chưa đáp ứng đủ yêu cầu đã nêu. Mình muốn điều chỉnh yêu cầu nào ạ?'
        return 'Em chưa xác minh đủ giá và tồn kho cho đúng lựa chọn của mình nên chưa thể tạo đơn ạ.'
    promo = safe_promotion_reply(state)
    text = _search_text(state.get('safe_text', ''))
    price_requested = bool(re.search(r'gia|bao nhieu', text))
    price = safe_quote_reply(state) if price_requested else None
    explanation = None
    # A specifically referenced code can be classified; unrelated expiry is not evidence.
    codes = set(re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", state.get('safe_text', '')))
    focus = decision.focus_sku
    for call in build_commerce_evidence(state):
        if call.get('name') != 'pricing.get_quote' or 'error' in call.get('result', {}):
            continue
        if focus and call.get('args', {}).get('sku') != focus:
            continue
        result = call['result']
        for code in sorted(codes):
            if code in result.get('expired_promos', []):
                explanation = f'Mã {code} đã hết hạn. '
            elif any(p.get('promo_code') == code for p in result.get('ineligible_promos', [])):
                explanation = f'Mã {code} không đủ điều kiện cho báo giá hiện tại. '
            elif any((p.get('promo_code') if isinstance(p, dict) else p) == code
                     for p in result.get('not_applied_exclusive', [])):
                explanation = f'Mã {code} không được cộng dồn trong báo giá hiện tại. '
    parts = [p for p in (price, explanation, promo) if p]
    return mask_pii(' '.join(parts)) if parts else None



def safe_followup_reply(state: dict, task=None) -> str | None:
    """Recovery for the requested information; it never modifies speech or grants consent."""
    from app.mcp_servers.mcp_shared.consultation_followup import (
        followup_task, policy_call_for_task, compatible_quote, offer_changes,
    )
    from app.mcp_servers.mcp_shared.commerce_rules import _search_text
    task = task or followup_task(state)
    if task.kind == 'none':
        return None
    if task.kind == 'policy':
        if task.missing_fields:
            return 'Em cần xác minh đơn hàng của mình trước khi xác nhận quyền lợi áp dụng cho đơn ạ.'
        call = policy_call_for_task(state, task)
        result = call.get('result', {}) if call else {}
        status = result.get('retrieval_status')
        if status in {'unavailable', 'timeout', 'overloaded'} or result.get('error'):
            return 'Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.'
        evidence_set = result.get('evidence_set') or {}
        if evidence_set.get('required_dependencies_complete') is False or evidence_set.get('missing_required_section_ids'):
            return 'Em chưa xác minh đầy đủ điều kiện và ngoại lệ của chính sách cho câu hỏi này ạ.'
        query = _search_text(task.policy_query or '')
        # Accent folding conflates đổi (exchange) with đối (competitor).
        # Match the policy topic, not a substring in an unrelated playbook hit.
        topic = (r'\bbảo hành\b' if 'bao hanh' in query else
                 r'\bđổi\s+(?:trả|size|sản phẩm|mới)\b' if 'doi' in query else
                 r'\bphí\b' if 'phi' in query else None)
        paragraphs = []
        for row in result.get('evidence', []):
            app = row.get('applicability') or {}
            content = row.get('content')
            if (not isinstance(content, str) or row.get('evidence_type', 'business_rule') != 'business_rule'
                    or app.get('status', 'applicable') != 'applicable'
                    or app.get('missing_required_section_ids')):
                continue
            folded = _search_text(content)
            if topic and not re.search(topic, content, re.IGNORECASE):
                continue
            if not re.search(r'\d|mien phi|khong bao hanh|khong ap dung|dieu kien|loi ky thuat', folded):
                continue
            if content not in paragraphs:
                paragraphs.append(content.strip())
        # Do not truncate policy text and silently drop exceptions or quote operational guides.
        if not paragraphs or len(' '.join(paragraphs)) > 1400:
            return 'Em chưa xác minh được thông tin chính sách đủ rõ để trả lời câu hỏi này. Mình cho em làm rõ điều kiện cần áp dụng nhé?'
        answer = 'Theo thông tin chính sách đã kiểm tra: ' + ' '.join(paragraphs)
        if re.search(r'\bgia\b', _search_text(state.get('safe_text', ''))):
            price = safe_quote_reply(state)
            if price:
                answer = price + ' ' + answer
        return mask_pii(answer)
    if not task.focus_sku:
        return 'Mình đang cân nhắc sản phẩm nào để em kiểm tra đúng quyền lợi hiện tại ạ?'
    call = compatible_quote(state, task.focus_sku)
    if call is None:
        return 'Em ghi nhận mình còn cân nhắc về mức giá. Em chưa xác minh được giá và quyền lợi hiện tại cho sản phẩm này ạ.'
    from app.mcp_servers.mcp_shared.consultation import catalog_items
    result = call.get('result', {})
    price = result.get('final_price_vnd')
    if type(price) is not int:
        return 'Em chưa xác minh được báo giá hiện tại cho sản phẩm mình đang cân nhắc ạ.'
    items = catalog_items(state)
    label = items.get(task.focus_sku, {}).get('name')
    if not label:
        return 'Em chưa xác minh đủ thông tin sản phẩm để đối chiếu quyền lợi hiện tại ạ.'
    answer = f"Mình đang cân nhắc {label} và mức giá. Giá hiện tại của {label} là {price:,}đ.".replace(',', '.')
    benefits = []
    for promo in result.get('applied_promos', []):
        if not isinstance(promo, dict):
            continue
        if promo.get('type') == 'gift':
            gift = items.get(promo.get('gift_sku'), {}).get('name')
            benefits.append(f"tặng {promo.get('qty', 1)} {gift}" if gift else 'tặng quà kèm theo')
        elif type(promo.get('discount_vnd')) is int and promo['discount_vnd'] > 0:
            benefits.append(f"giảm {promo['discount_vnd']:,}đ".replace(',', '.'))
        if promo.get('type') == 'freecod':
            benefits.append('miễn phí thu hộ COD')
    if result.get('freeship') is True:
        benefits.append('miễn phí vận chuyển')
    if benefits:
        answer += ' Báo giá hiện tại kèm ' + ', '.join(dict.fromkeys(benefits)) + '.'
    elif not result.get('applied_promos'):
        answer += ' Hiện không có chương trình khuyến mãi áp dụng trong báo giá này.'
    else:
        answer += ' Em chưa xác minh đủ chi tiết quyền lợi để mô tả thêm.'
    labels, higher, worse = offer_changes(state, task.focus_sku, result)
    for code, status in labels:
        if status == 'expired': answer += f' Mã {code} đã hết hạn.'
        elif status == 'ineligible': answer += f' Mã {code} không đủ điều kiện cho báo giá hiện tại.'
        elif status == 'exclusive': answer += f' Mã {code} không được cộng dồn trong báo giá hiện tại.'
        elif 'Em chưa xác minh được tình trạng mã trước đây.' not in answer:
            answer += ' Em chưa xác minh được tình trạng mã trước đây.'
    if higher:
        answer += ' Giá hiện tại cao hơn mức đã báo trước đó.'
    elif worse:
        answer += ' Quyền lợi hiện tại không còn như báo giá đã trao đổi trước đó.'
    if higher or worse:
        answer += ' Mình có đồng ý với giá và quyền lợi hiện tại trước khi tiếp tục đặt hàng không ạ?'
    else:
        answer += ' Với quyền lợi hiện tại, mình muốn tiếp tục cân nhắc phương án này không ạ?'
    return mask_pii(answer)


class SessionNodes:
    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int, prompt_history_turns: int,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_tool_calls = max_tool_calls
        self.prompt_history_turns = prompt_history_turns
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @trace_node("accept")
    async def accept(self, state: TurnState) -> dict[str, Any]:
        return {
            "safe_text": mask_pii(state["request"].text),
            "received_at_monotonic": state.get("received_at_monotonic", time.perf_counter()),
            "tool_calls": state.get("tool_calls", []), "tool_count": 0,
            "tool_failed": False,
            "needs_handoff": False, "handoff_ticket_id": None,
        }

    @trace_node("retrieve_context")
    async def retrieve_context(self, state: TurnState) -> dict[str, Any]:
        result = await load_context(state, self.memory, self.tools, self.clock)
        log_event(state, "retrieve_context", "context_loaded",
                  history_turns=len(result.get("history", [])),
                  profile_facts=len(result.get("profile", {})),
                  episodes=len(result.get("episodes", [])),
                  call_brief=bool(result.get("call_brief")),
                  success=not result.get("tool_failed", False))
        return result
