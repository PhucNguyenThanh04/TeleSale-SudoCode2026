"""Verify each spoken offer against its product quote, never another benefit."""
import re
from datetime import date
from typing import Any

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.agent.guardrails.claims import assertion_text


def _fold(text: str) -> str:
    return _search_text(text)


def _named(text: str, name: str) -> bool:
    return bool(re.search(r"(?<![\w-])" + re.escape(_fold(name)) + r"(?![\w-])", _fold(text)))


def _gift_supported(clause: str, promos: list[dict], items: list[dict]) -> bool:
    gifts = [p for p in promos if p.get("type") == "gift" and p.get("gift_sku")]
    if not gifts:
        return False
    folded = _fold(clause)
    count = re.search(r"(?:tang|bieu)\s+(?:kem\s+)?(\d+|mot|hai|ba|bon|nam)\b", folded)
    if count:
        number = int(count[1]) if count[1].isdigit() else {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5}[count[1]]
        gifts = [p for p in gifts if p.get("gift_qty", 1) == number]
    if not gifts:
        return False
    # A generic gift is supportable without guessing its name from its SKU.
    if re.search(r"\btang (?:qua|kem qua)|\bqua tang\b", folded):
        return True
    match = re.search(r"(?:tang|bieu)\s+(?:kem\s+)?(?:(?:\d+|mot|hai|ba|bon|nam)\s+)?(.+)", folded)
    if not match:
        return False
    description = re.split(r"\b(?:va|den|cho|theo|tri gia|co han|nay|a|nhe|roi)\b|[,;]", match[1])[0].strip()
    if not description:
        return False
    names = [str(item.get("name", "")) for item in items
             if any(item.get("sku") == p.get("gift_sku") for p in gifts)]
    return any(len(description.split()) >= 2 and description in _fold(name) for name in names)


def check_promotion_grounding(candidate: str, tool_calls: list[dict[str, Any]], *, focus_sku: str | None = None) -> str | None:
    candidate = assertion_text(candidate)
    successful = [c for c in tool_calls if isinstance(c.get("result"), dict) and "error" not in c["result"]]
    items = [item for c in successful if c.get("name") == "catalog.search"
             for item in c["result"].get("items", []) if isinstance(item, dict)]
    quotes = [c for c in successful if c.get("name") == "pricing.get_quote"]
    order_ids = {str(row['order_id']) for call in successful
                 for row in [call['result'], *call['result'].get('orders', [])]
                 if isinstance(row, dict) and row.get('order_id')}
    # A complete attributed policy section explains general conditions; it does
    # not assert that a promotion has been applied to this customer's order.
    from app.agent.guardrails.policy_grounding import policy_evidence_for_answer
    normalize = lambda value: ' '.join(re.sub(r'[*`_]', '', value).split())
    policy_sections = []
    if candidate.startswith('Theo thông tin chính sách đã kiểm tra:'):
        policy_sections = [normalize(row['content'].split('\n\n', 1)[-1])
            for row in policy_evidence_for_answer(candidate, successful)]
        policy_sections = [section for section in policy_sections if section and section in normalize(candidate)]
    for clause in re.split(r"\.(?!\d)|[;!\n]|\bnhưng\b|,\s*(?=(?:hôm nay|hiện tại)\b)", candidate):
        if normalize(clause) and any(normalize(clause) in section for section in policy_sections):
            continue
        folded = _fold(clause)
        # Product benefits such as "giảm bụi" / "tăng chất lượng" are not offers.
        commercial = _fold(re.sub(r'\btăng\b', '', clause, flags=re.IGNORECASE))
        # Biểu mẫu (form) is not biếu (a promotional gift) after accent folding.
        commercial = re.sub(r'\bbieu mau\b', '', commercial)
        commercial = re.sub(r'\bgiam\s+(?:bui|min|on|mui|vi khuan)\b', '', commercial)
        if "?" in clause or re.search(r"\b(?:lan truoc|truoc day)\b", folded) and not re.search(r"\b(?:hien|hom nay|dang)\b", folded):
            continue
        codes = {code for code in re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
                 if not code.startswith(("SKU-", "OD-")) and code not in order_ids}
        if not codes and not re.search(r"\b(?:khuyen mai|uu dai|giam|tang|bieu|freeship|mien phi (?:ship|van chuyen))\b", commercial):
            continue
        if any(call.get('name') == 'pricing.quote_order' for call in successful):
            from app.mcp_servers.mcp_shared.basket import basket_unit_quote
            unit = basket_unit_quote(clause, successful)
            baskets = [call for call in successful if call.get('name') == 'pricing.quote_order']
            if (unit is None and len(baskets) == 1
                    and re.search(r'freeship|mien phi (?:ship|van chuyen)', folded)
                    and not re.search(r'\b(?:giam|tang|bieu)\b|%', commercial)):
                basket = baskets[0]
                # Shipping belongs to the order; it does not grant a unit discount.
                unit = {'name': 'pricing.get_quote', 'args': {'on': basket.get('args', {}).get('on')},
                        'result': {'applied_promos': basket['result'].get('order_promos', []),
                                   'freeship': basket['result'].get('freeship', False)}}
            if unit is None:
                return 'promotion_quote_missing'
            reason = check_promotion_grounding(clause,
                [call for call in successful if call.get('name') not in {'pricing.get_quote', 'pricing.quote_order'}] + [unit],
                focus_sku=focus_sku)
            if reason:
                return reason
            continue
        from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
        mentioned = resolve_claim_skus(clause, successful, focus_sku=focus_sku)
        selected = [c for c in quotes if not mentioned or c.get('args', {}).get('sku') in mentioned]
        if len(mentioned) > 1 and len(selected) == 1:
            # Multiple variants without a sourced focus are still ambiguous.
            parent = selected[0].get('args', {}).get('sku')
            if not any(item.get('sku') == parent for item in items):
                return "promotion_quote_missing"
        if not selected or len({c.get("args", {}).get("sku") for c in selected}) != 1:
            return "promotion_quote_missing"
        # Conflicting quotes for the selected item are ambiguous evidence.
        if len({str((c.get("args"), c["result"])) for c in selected}) != 1:
            return "promotion_quote_missing"
        call = selected[-1]
        result = call["result"]
        promos = [p for p in result.get("applied_promos", []) if isinstance(p, dict)]
        on = call.get("args", {}).get("on")
        promos = [p for p in promos if not (on and p.get("valid_until") and p["valid_until"] < on)]
        inactive = bool(re.search(r"het han|het hieu luc|khong con|khong du dieu kien|khong (?:co|duoc)|chua (?:co|duoc)", folded))
        applied_codes = {p.get("promo_code") for p in promos}
        expired_codes = {p.get('promo_code') if isinstance(p, dict) else p
                         for p in result.get('expired_promos', [])}
        ineligible_codes = {p.get('promo_code') for p in result.get('ineligible_promos', [])
                            if isinstance(p, dict)}
        exclusive_codes = {p.get('promo_code') if isinstance(p, dict) else p
                           for p in result.get('not_applied_exclusive', [])}
        if inactive and not codes and re.search(r'uu dai cu|khuyen mai cu|ma cu|het han|het hieu luc', folded):
            return 'promotion_detail_unverified'
        if inactive and not codes and re.search(r'khong (?:co|con).*(?:khuyen mai|uu dai)', folded) and promos:
            return 'promotion_detail_unverified'
        if codes:
            if inactive:
                supported = (expired_codes if re.search(r'het han|het hieu luc', folded)
                             else ineligible_codes if 'khong du dieu kien' in folded
                             else exclusive_codes if re.search(r'cong don|doc quyen', folded)
                             else expired_codes | ineligible_codes | exclusive_codes)
                if codes & applied_codes or not codes <= supported:
                    return 'promotion_code_mismatch'
            elif not codes <= applied_codes:
                return 'promotion_code_mismatch'
            if not inactive:
                promos = [p for p in promos if p.get('promo_code') in codes]
        shipping = bool(re.search(r"freeship|mien phi (?:ship|van chuyen)", folded))
        gift = bool(re.search(r"\b(?:tang|bieu)\b", commercial))
        discount = bool(re.search(r"\bgiam\b", commercial))
        if inactive and not codes and (gift and any(p.get("type") == "gift" for p in promos)
                                      or shipping and result.get("freeship") is True):
            return "promotion_detail_unverified"
        if shipping and not inactive and result.get("freeship") is not True:
            return "promotion_detail_unverified"
        if gift and not inactive and not _gift_supported(clause, promos, items):
            return "promotion_detail_unverified"
        discounts = [p.get("discount_vnd", 0) for p in promos if type(p.get("discount_vnd", 0)) is int]
        if discount and not inactive:
            # "không giảm thêm" does not assert a new discount.
            negative = re.search(r"(?:khong|chua)\s+(?:con\s+|duoc\s+|co\s+)?giam", folded)
            if not negative and not any(d > 0 for d in discounts):
                return "promotion_detail_unverified"
        percentages = [float(n.replace(",", ".")) for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", clause)]
        if percentages and not inactive:
            base = result.get("list_price_vnd")
            if type(base) is not int or base <= 0 or any(not any(
                    abs(base * percent / 100 - d) <= 1 for d in discounts) for percent in percentages):
                return "promotion_detail_unverified"
        deadlines = re.findall(r"(?:đến|hạn(?:\s+đến)?)\s+(?:ngày\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", clause, re.I)
        for day, month, year in deadlines:
            try:
                expiry = date(int(year or str(on)[:4]), int(month), int(day)).isoformat()
            except (ValueError, TypeError):
                return "promotion_detail_unverified"
            benefit_sets = []
            if gift:
                benefit_sets.append([p for p in promos if p.get("type") == "gift"])
            if discount:
                benefit_sets.append([p for p in promos if p.get("discount_vnd", 0) > 0])
            if shipping:
                benefit_sets.append([p for p in promos if p.get("type") == "freeship"])
            if not benefit_sets:
                benefit_sets = [promos]
            if any(not any(p.get("valid_until") == expiry for p in benefits) for benefits in benefit_sets):
                return "promotion_detail_unverified"
        if not inactive and not (promos or shipping and result.get("freeship")):
            return "promotion_unverified"
    return None
