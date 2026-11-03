"""Verify each spoken offer against its product quote, never another benefit."""
import re
from datetime import date
from typing import Any

from app.mcp_servers.mcp_shared.commerce_rules import _search_text


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


def check_promotion_grounding(candidate: str, tool_calls: list[dict[str, Any]]) -> str | None:
    successful = [c for c in tool_calls if isinstance(c.get("result"), dict) and "error" not in c["result"]]
    items = [item for c in successful if c.get("name") == "catalog.search"
             for item in c["result"].get("items", []) if isinstance(item, dict)]
    quotes = [c for c in successful if c.get("name") == "pricing.get_quote"]
    for clause in re.split(r"\.(?!\d)|[;!\n]|\bnhưng\b|,\s*(?=(?:hôm nay|hiện tại)\b)", candidate):
        folded = _fold(clause)
        if "?" in clause or re.search(r"\b(?:lan truoc|truoc day)\b", folded) and not re.search(r"\b(?:hien|hom nay|dang)\b", folded):
            continue
        codes = {code for code in re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
                 if not code.startswith(("SKU-", "OD-"))}
        if not codes and not re.search(r"khuyen mai|uu dai|giam|tang|bieu|freeship|mien phi (?:ship|van chuyen)", folded):
            continue
        mentioned = {c.get("args", {}).get("sku") for c in quotes
                     if _named(clause, str(c.get("args", {}).get("sku", ""))) or any(
                         item.get("sku") == c.get("args", {}).get("sku") and item.get("name")
                         and _named(clause, item["name"]) for item in items)}
        selected = [c for c in quotes if not mentioned or c.get("args", {}).get("sku") in mentioned]
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
        inactive = bool(re.search(r"het han|het hieu luc|khong con|khong (?:co|duoc)|chua (?:co|duoc)", folded))
        applied_codes = {p.get("promo_code") for p in promos}
        if codes:
            if inactive:
                if codes & applied_codes or not codes <= set(result.get("expired_promos", [])) | {
                        p.get("promo_code") for p in result.get("ineligible_promos", [])}:
                    return "promotion_code_mismatch"
            elif not codes <= applied_codes:
                return "promotion_code_mismatch"
            if not inactive:
                promos = [p for p in promos if p.get("promo_code") in codes]
        shipping = bool(re.search(r"freeship|mien phi (?:ship|van chuyen)", folded))
        gift = bool(re.search(r"tang|bieu", folded))
        discount = bool(re.search(r"\bgiam\b", folded))
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
