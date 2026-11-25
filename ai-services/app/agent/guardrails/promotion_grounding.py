from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS
import re
from datetime import date
from typing import Any

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.agent.guardrails.claims import assertion_text


_FREE_SHIPPING = re.compile(r"\b(?:freeship|mien phi (?:ship|van chuyen))\b")
_FREE_COD = re.compile(r"\bmien phi (?:cod|thu ho)\b")


def _fold(text: str) -> str:
    return _search_text(re.sub(r'[*`]|__', '', text))


def _named(text: str, name: str) -> bool:
    return bool(re.search(r"(?<![\w-])" + re.escape(_fold(name)) + r"(?![\w-])", _fold(text)))


def _gift_claim(clause: str):
    return re.search(r'\b(?:tang|bieu)\b(?:\s*:)?\s*(?:kem\b\s*)?'
        r'(?:(?P<count>\d+|mot|hai|ba|bon|nam)\b\s*)?(?:qua\b\s*)?(?:la\b\s*)?'
        r'(?P<description>.*?)(?=\s+\b(?:va|den|cho|theo|tri gia|co han|nay|a|nhe|roi|khi mua)\b|[,;]|$)',
        _fold(clause))


_PASSIVE_GIFT = re.compile(r'\bduoc\s+(?:tang|bieu)\s+kem\b')


def _passive_gift_match(clause: str):
    folded = _fold(clause)
    match = _PASSIVE_GIFT.search(folded)
    if not match:
        return None
    before = folded[:match.start()]
    after = folded[match.end():].strip()
    if after and not re.match(r'^(?:theo|se|duoc|voi|trong|cung|cho|khi|a|nhe|roi|va)\b', after):
        return None
    return match, before


def _promotion_subject(clause: str) -> str:
    folded = _fold(clause)
    passive = _passive_gift_match(clause)
    if passive:
        match, before = passive
        parts = re.split(r'(?:,\s*(?:thi\s+)?|\bthi\b\s+)', before)
        if len(parts) > 1:
            return ' '.join(parts[:-1]) + folded[match.end():]
        return folded[match.end():]
    claim = _gift_claim(clause)
    if claim:
        start, end = claim.span('description')
        return folded[:start] + folded[end:]
    return folded


def _gift_supported(clause: str, promos: list[dict], items: list[dict]) -> bool:
    gifts = [p for p in promos if p.get("type") == "gift" and p.get("gift_sku")]
    if not gifts:
        return False
    folded = _fold(clause)
    names = [str(item.get("name", "")) for item in items
             if item.get('name') and any(item.get("sku") == p.get("gift_sku") for p in gifts)]
    passive = _passive_gift_match(clause)
    if passive:
        _, before = passive
        subject = re.split(r'(?:,\s*(?:thi\s+)?|\bthi\b\s+)', before)[-1].strip()
        subject = re.sub(r'^(?:da|vang)[,\s]+', '', subject).strip()
        subject = re.sub(r'^(?:cai|chiec|bo|phan|mon)\s+', '', subject).strip()
        if not subject or re.fullmatch(r'qua(?:\s+tang)?', subject):
            return True
        return any(_named(subject, name) or len(subject.split()) >= 2 and _named(name, subject)
                   for name in names)
    claim = _gift_claim(clause)
    if not claim:
        return False
    count = claim['count']
    if count:
        number = int(count) if count.isdigit() else {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5}[count]
        gifts = [p for p in gifts if p.get("gift_qty", 1) == number]
    if not gifts:
        return False
    description = claim['description'].strip()
    if re.fullmatch(r'(?:a|nhe|nha|nhi)', description):
        description = ''
    if not description:
        return bool(re.search(r"\btang (?:qua|kem qua)|\bqua tang\b", folded))
    descriptions = [description]
    without_address = re.sub(r'\s+(?:anh|chi|em)(?:\s+(?:a|nhe))?$', '', description)
    descriptions.append(re.sub(r'\s+mien phi$', '', without_address))
    descriptions += [re.sub(r'^(?:cai|chiec|bo)\s+', '', value) for value in descriptions]
    return any(_named(value, name) or len(value.split()) >= 2 and _named(name, value)
               for value in descriptions for name in names)


def check_promotion_grounding(candidate: str, tool_calls: list[dict[str, Any]], *, focus_sku: str | None = None) -> str | None:
    candidate = re.sub(r'[*`]|__', '', assertion_text(candidate))
    successful = [c for c in tool_calls if isinstance(c.get("result"), dict) and "error" not in c["result"]]
    items = [item for c in successful if c.get("name") in CATALOG_TOOLS
             for item in c["result"].get("items", []) if isinstance(item, dict)]
    quotes = [c for c in successful if c.get("name") == "pricing.get_quote"]
    from app.agent.guardrails.skus import known_skus
    product_codes = known_skus(successful)
    model_tokens = {token for item in items if isinstance(item.get('name'), str)
                    for token in re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", item['name'])}
    order_ids = {str(row['order_id']) for call in successful
                 for row in [call['result'], *call['result'].get('orders', [])]
                 if isinstance(row, dict) and row.get('order_id')}
    from app.agent.guardrails.policy_grounding import policy_evidence_for_answer
    normalize = lambda value: ' '.join(re.sub(r'[*`_]', '', value).split())
    policy_sections = []
    if candidate.startswith('Theo thông tin chính sách đã kiểm tra:'):
        policy_sections = [normalize(row['content'].split('\n\n', 1)[-1])
            for row in policy_evidence_for_answer(candidate, successful)]
        policy_sections = [section for section in policy_sections if section and section in normalize(candidate)]
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    quoted_skus = {c.get('args', {}).get('sku') for c in quotes if c.get('args', {}).get('sku')}
    clauses = re.split(r"\.(?!\d)|[;!\n]|\bnhưng\b|,\s*(?=(?:hôm nay|hiện tại|tặng|biếu)\b)", candidate, flags=re.IGNORECASE)
    answer_skus = set()
    for _clause in clauses:
        answer_skus.update(resolve_claim_skus(_promotion_subject(_clause), successful, focus_sku=None))
    answer_quoted_skus = answer_skus & quoted_skus
    for clause in clauses:
        if normalize(clause) and any(normalize(clause) in section for section in policy_sections):
            continue
        folded = _fold(clause)
        commercial = _fold(re.sub(r'\btăng\b', '', clause, flags=re.IGNORECASE))
        commercial = re.sub(r'\bbieu mau\b', '', commercial)
        commercial = re.sub(r'\bgiam\s+(?:bui|min|on|mui|vi khuan)\b', '', commercial)
        if "?" in clause or re.search(r"\b(?:lan truoc|truoc day)\b", folded) and not re.search(r"\b(?:hien|hom nay|dang)\b", folded):
            continue
        if (re.search(r"\bchua\s+(?:co|nhan duoc|cap nhat duoc|xac minh duoc|tra cuu duoc)\s+(?:thong tin|du lieu)\b", folded)
                and not re.search(r"\b(?:giam|tang|bieu|het han|het hieu luc)\b|%|\d", commercial)
                and not (_FREE_SHIPPING.search(folded) or _FREE_COD.search(folded))):
            continue
        codes = {code for code in re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
                 if not code.startswith(("SKU-", "OD-")) and code not in order_ids | product_codes | model_tokens}
        shipping = bool(_FREE_SHIPPING.search(folded))
        cod = bool(_FREE_COD.search(folded))
        if not (codes or shipping or cod or re.search(r"\b(?:khuyen mai|uu dai|giam|tang|bieu)\b", commercial)):
            continue
        if any(call.get('name') == 'pricing.quote_order' for call in successful):
            from app.mcp_servers.mcp_shared.basket import basket_unit_quote
            unit = basket_unit_quote(_promotion_subject(clause), successful, focus_sku=focus_sku)
            baskets = [call for call in successful if call.get('name') == 'pricing.quote_order']
            if unit is not None and cod and len(baskets) == 1:
                unit['result']['applied_promos'].extend(
                    promo for promo in baskets[0]['result'].get('order_promos', [])
                    if promo.get('type') == 'freecod')
            if (unit is None and len(baskets) == 1 and (cod or shipping)
                    and not re.search(r'\b(?:giam|tang|bieu)\b|%', commercial)):
                basket = baskets[0]
                sku = focus_sku
                if sku and not any(row.get('sku') == sku for row in basket['result'].get('units', [])):
                    return 'promotion_quote_missing'
                unit = {'name': 'pricing.get_quote', 'args': {'on': basket.get('args', {}).get('on'), 'sku': sku},
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
        mentioned = resolve_claim_skus(_promotion_subject(clause), successful, focus_sku=None)
        if not mentioned:
            mentioned = answer_quoted_skus if len(answer_quoted_skus) == 1 else (
                {focus_sku} if focus_sku else set())
        selected = [c for c in quotes if not mentioned or c.get('args', {}).get('sku') in mentioned]
        if len(mentioned) > 1 and len(selected) == 1:
            parent = selected[0].get('args', {}).get('sku')
            if not any(item.get('sku') == parent for item in items):
                return "promotion_quote_missing"
        if not selected or len({c.get("args", {}).get("sku") for c in selected}) != 1:
            return "promotion_quote_missing"
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
        cod_supported = any(p.get("type") == "freecod" for p in promos)
        gift = bool(re.search(r"\b(?:tang|bieu)\b", commercial))
        discount = bool(re.search(r"\bgiam\b", commercial))
        if inactive and not codes and (gift and any(p.get("type") == "gift" for p in promos)
                                      or shipping and result.get("freeship") is True or cod and cod_supported):
            return "promotion_detail_unverified"
        if shipping and not inactive and result.get("freeship") is not True:
            return "promotion_detail_unverified"
        if cod and not inactive and not cod_supported:
            return "promotion_detail_unverified"
        if gift and not inactive and not _gift_supported(clause, promos, items):
            return "promotion_detail_unverified"
        discounts = [p.get("discount_vnd", 0) for p in promos if type(p.get("discount_vnd", 0)) is int]
        if discount and not inactive:
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
            if cod:
                benefit_sets.append([p for p in promos if p.get("type") == "freecod"])
            if not benefit_sets:
                benefit_sets = [promos]
            if any(not any(p.get("valid_until") == expiry for p in benefits) for benefits in benefit_sets):
                return "promotion_detail_unverified"
        if not inactive and not (promos or shipping and result.get("freeship")):
            return "promotion_unverified"
    return None
