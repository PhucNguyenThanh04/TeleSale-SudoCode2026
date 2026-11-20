
import json
import re
from pathlib import Path
from typing import Any

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.mcp_servers.mcp_shared.pii import mask_pii as _base_mask_pii
from eval_harness.trace_evidence import SENSITIVE_NUMBER
from eval_harness.extractor import build_trace_row, extract_questions, extract_claims
from copy import deepcopy
from app.agent.guardrails.checks import _money_claims


_SCORER_ARG_FIELDS = frozenset({
    "sku", "price_vnd", "payment", "order_id", "new_variant_sku", "action", "query"
})


def mask_pii(value: str) -> str:
    return _base_mask_pii(SENSITIVE_NUMBER.sub(r"\1[SỐ ĐÃ ẨN]", value))


def _safe_value(value: Any, path: tuple[str, ...] = ()) -> Any:
    if type(value) is int and path == ("memory_writes", "value") and 10 <= len(str(abs(value))) <= 14:
        return "[SỐ ĐÃ ẨN]"
    if isinstance(value, str):
        if path in {("args", "customer_name"), ("result", "customer_name")}:
            return "[TÊN ĐÃ ẨN]"
        if path in {("args", "customer_phone"), ("args", "phone"),
                    ("result", "customer_phone"), ("result", "phone")}:
            return "[SỐ ĐÃ ẨN]"
        if path in {("args", "address"), ("result", "address"), ("args", "source_identity"), ("result", "source_identity"),
                    ("args", "brief", "customer_name"), ("args", "brief", "customer_phone"),
                    ("args", "brief", "address"),
                    ("args", "brief", "facts_confirmed", "address"),
                    ("args", "brief", "facts_confirmed", "shipping_address"),
                    ("args", "brief", "facts_confirmed", "customer_phone"),
                    ("args", "brief", "facts_confirmed", "customer_name"), ("result", "name"),
                    ("result", "customer", "name")}:
            return "[PII ĐÃ ẨN]"
        if path == ("result", "order_id"):
            return value
        if len(path) == 2 and path[0] == "args" and path[1] in _SCORER_ARG_FIELDS:
            return mask_pii(value) if path[1] == "query" else value
        return mask_pii(value)
    if isinstance(value, list):
        return [_safe_value(item, path) for item in value]
    if isinstance(value, dict):
        return {child_key: _safe_value(item, (*path, child_key))
                for child_key, item in value.items()}
    return value


def _mask_names(value, names):
    if isinstance(value, str):
        for name in names:
            if name and len(name) > 1:
                value = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", "[TÊN ĐÃ ẨN]", value, flags=re.I)
        return value
    if isinstance(value, list):
        return [_mask_names(v,names) for v in value]
    if isinstance(value, dict):
        return {k: (v if k in {"name","id","call_id"} and ("args" in value or "result" in value)
                    else _mask_names(v,names)) for k,v in value.items()}
    return value


def _safe_tool_calls(tool_calls: list[dict]) -> list[dict]:
    result = []
    for call in tool_calls:
        tool_name = call.get("name")
        args = _safe_value(call.get("args") or {}, ("args",))
        safe_call = {
            "name": tool_name,
            "args": args,
            "result": _safe_value(call.get("result") or {}, ("result",))
        }
        for identifier in ("id", "call_id"):
            if identifier in call:
                safe_call[identifier] = call[identifier]
        result.append(safe_call)
    names = set()
    for call in tool_calls:
        args = call.get("args") or {}
        for obj in (args, args.get("brief") or {}, call.get("result") or {}):
            for key in ("customer_name", "name"):
                if isinstance(obj.get(key),str):
                    names.add(obj[key])
    return _mask_names(result,names)


def _source_session_id(source: Any) -> str | None:
    if not isinstance(source, str):
        return None
    parts = source.split(":")
    if any(not part or part.strip() != part or re.search(r"\s", part) for part in parts):
        return None
    if parts[0] == "langmem":
        return parts[1] if len(parts) == 3 and all(parts) else None
    return parts[0] if len(parts) == 2 and all(parts) else None


def _fold(value: str) -> str:
    return _search_text(value)


def _spoken_fact(key: str, value: Any, text: str) -> bool:
    folded = _fold(text)
    if type(value) is bool:
        if key == "has_children":
            negative = bool(re.search(r"\b(?:khong|chua)\s+(?:co\s+)?(?:tre nho|con nho|em be|be nho)\b", folded))
            positive = bool(re.search(r"\b(?:co\s+(?:tre nho|con nho|em be|be nho)|be nha minh)\b", folded))
        elif key == "in_stock":
            negative = bool(re.search(r"\b(?:het hang|tam het hang)\b", folded))
            positive = bool(re.search(r"\b(?:con hang|co hang|san hang)\b", folded))
        else:
            return False
        return negative if not value else positive and not negative
    if key.endswith("_vnd"):
        expected_kind = "competitor" if key == "competitor_price_vnd" else "price"
        if key == "budget_vnd" and not re.search(r"ngan sach|tam tien|tam gia", folded):
            return False
        money_text = re.sub(r"(?<=\d)d\b", "đ", text)
        for plain, original in (("trieu", "triệu"), ("nghin", "nghìn"), ("ngan", "ngàn"), ("dong", "đồng")):
            money_text = re.sub(r"\b" + plain + r"\b", original, money_text)
        return any(amount == value and kind == expected_kind for amount, kind, _ in _money_claims(money_text))
    if key == "room_area_m2":
        return bool(re.search(r"(?<![\w.])" + re.escape(str(value)) + r"\s*(?:m2|m²|met vuong)(?!\w)", folded))
    if key == 'objection' and value == 'dat_qua':
        return bool(re.search(r'\bdat_qua\b|\bgia\b.{0,40}\b(?:cao|dat)\b', folded)
                    and not re.search(r'\b(?:khong|chua)\b.{0,15}\b(?:cao|dat)\b', folded))
    if key == "blocker" and isinstance(value, str):
        from app.agent.memory.decision_makers import roles_mentioned
        roles = roles_mentioned(_fold(value))
        if roles and re.search(r"\b(?:hoi|ban|trao doi)\b", _fold(value)):
            return (roles_mentioned(folded) == roles and
                    bool(re.search(r"\b(?:can|phai|cho|doi)\b", folded)) and
                    bool(re.search(r"\b(?:hoi|ban|trao doi)\b", folded)) and
                    not re.search(r"dong y roi|da .{0,40}(?:xong|dong y)|khong (?:con )?can", folded))
    return isinstance(value, (str, int)) and bool(re.search(
        r"(?<![\w-])" + re.escape(_fold(str(value))) + r"(?![\w-])", folded))


_ROOM_ALIASES = {
    "bedroom": ("bedroom", "bed room", "phong ngu"),
    "living_room": ("living room", "living_room", "phong khach"),
    "kitchen": ("kitchen", "bep", "phong bep"),
    "dining_room": ("dining room", "dining_room", "phong an"),
    "office": ("office", "phong lam viec"),
    "bathroom": ("bathroom", "phong tam"),
}


def _literal_pattern(value: str) -> str:
    return r"(?<![\w-])" + re.escape(value) + r"(?![\w-])"


def _scope_units(text: str, scope_type: str | None, scope_id: str | None, catalog_calls=()):
    for clause in re.split(r"[!?;\n]|\.(?!\d)|,\s*(?!\d)", text):
        if scope_id is None:
            yield clause
        elif scope_type == "room":
            folded_id = _fold(str(scope_id))
            aliases = _ROOM_ALIASES.get(folded_id, (folded_id,))
            room_pattern = "|".join(_literal_pattern(alias) for alias in sorted(
                {alias for group in _ROOM_ALIASES.values() for alias in group} | set(aliases), key=len, reverse=True)) + r"|\bphong\b|\broom\b"
            mentions = list(re.finditer(room_pattern, clause))
            for i, mention in enumerate(mentions):
                if mention.group() in aliases:
                    yield clause if len(mentions) == 1 else clause[mention.start():mentions[i+1].start() if i+1 < len(mentions) else len(clause)]
        elif scope_type == 'product':
            from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
            named = resolve_claim_skus(clause, catalog_calls)
            parents = {variant.get('variant_sku'): item.get('sku')
                       for call in catalog_calls for item in call.get('result', {}).get('items', [])
                       if isinstance(item, dict) for variant in item.get('variants') or []
                       if isinstance(variant, dict)}
            parent_names = {parents.get(sku, sku) for sku in named}
            if not re.search(_literal_pattern(_fold(str(scope_id))), clause):
                if parent_names == {scope_id}:
                    yield clause
                continue
            mentions = list(re.finditer(r"(?<![\w-])sku-[\w-]+", clause))
            aliases = resolve_claim_skus(re.sub(r'(?<![\w-])sku-[\w-]+', '', clause), catalog_calls)
            if aliases and not {_fold(sku) for sku in aliases} <= {m.group() for m in mentions}:
                continue
            if len(mentions) == 1 and len(named) > 1:
                continue
            matching = [i for i,m in enumerate(mentions) if m.group() == _fold(str(scope_id))]
            if matching:
                for i in matching:
                    yield clause[mentions[i].start():mentions[i+1].start() if i+1 < len(mentions) else len(clause)]
            else:
                yield clause


def _speech_uses(text, key, value, scope_type, scope_id, *, customer=False, catalog_calls=()):
    if not customer and key == "blocker" and ("?" in text or re.search(r"đúng không|phải không", text, re.I)):
        return False
    folded = _fold(re.sub(r"\*\*|__|`", "", text))
    for unit in _scope_units(folded, scope_type, scope_id, catalog_calls):
        if not customer and "?" in text and re.search(r"\b(?:hay|hoac)\b", unit):
            continue
        if re.search(r'[“”"«»]|\bneu\b', unit):
            continue
        unit = re.sub(r"khong phai.+?\bma(?: la)?\s*", "", unit)
        unit = re.split(r"\bchu khong(?: phai)?\b", unit)[0]
        if key not in {"has_children", "in_stock"} and re.search(r"\b(?:khong|chua) (?:phai|con|can|co|rong|la|bang)\b", unit):
            continue
        if key == 'product_advised' and isinstance(value, str):
            from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
            if resolve_claim_skus(unit, catalog_calls) == {value}:
                return True
        if _spoken_fact(key, value, unit):
            return True
    return False


def _argument_uses_fact(call, key, value, scope_type, scope_id, fields, catalog,
                        room_facts, customer_text):
    args = call.get('args', {})
    if call.get('name') == 'handoff.transfer' and key in {'product_advised', 'price_quoted_vnd'}:
        brief = args.get('brief') or {}
        if scope_type == 'room':
            return False
        if scope_type == 'product' and brief.get('product_advised') != scope_id:
            return False
        return type(brief.get(key)) is type(value) and brief[key] == value
    variants = []
    for c in catalog:
        for item in c['result'].get('items', []):
            if not isinstance(item, dict):
                continue
            for variant in item.get('variants') or []:
                if isinstance(variant, dict) and variant.get('variant_sku') == args.get('sku'):
                    entry = (item.get('sku'), variant.get('size'), variant.get('color'))
                    if entry not in variants:
                        variants.append(entry)
    variant = variants[0] if len(variants) == 1 else None
    if scope_type == 'product' and args.get('sku') != scope_id and not (
            variant and variant[0] == scope_id):
        return False
    if scope_type == 'room' and args.get('room') != scope_id:
        aliases = {**_ROOM_ALIASES, **{_fold(room): _ROOM_ALIASES.get(_fold(room), (_fold(room),))
                                     for room in room_facts}}
        mentioned = {room for room, labels in aliases.items() if any(
            re.search(_literal_pattern(label), _fold(customer_text)) for label in labels)}
        candidates = mentioned or {_fold(room) for room, facts in room_facts.items() if key in facts}
        if candidates != {_fold(scope_id)}:
            return False
    if call.get('name') == 'catalog.search':
        filter_field = {'budget_vnd': 'max_price_vnd', 'room_area_m2': 'min_room_area_m2'}.get(key)
        if filter_field and type(args.get(filter_field)) is type(value) and args[filter_field] == value:
            return True
    if variant:
        if key == 'product_advised' and value == variant[0]:
            return True
        index = {'size': 1, 'preferred_size': 1, 'color': 2, 'preferred_color': 2}.get(key)
        if index and variant[index] is not None and _fold(str(variant[index])) == _fold(str(value)):
            return True
    return any(type(arg) is type(value) and arg == value
               for field, arg in args.items() if field in fields)


def facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict,
               scoped_facts: dict | None = None,
               current_session_id: str | None = None, *, customer_text: str = "",
               catalog_calls: list[dict] | None = None,
               usage_evidence: list[dict] | None = None) -> list[str]:
    if not current_session_id:
        return []
    catalog = [c for c in (catalog_calls if catalog_calls is not None else tool_calls)
               if c.get('name') == 'catalog.search' and isinstance(c.get('result'), dict)
               and 'error' not in c['result'] and c['result'].get('ok') is not False
               and c['result'].get('success') is not False]
    candidates = [(key, fact, None, None) for key, fact in prior_facts.items()]
    for scope_type, scopes in (scoped_facts or {}).items():
        if scope_type not in {"product", "room"} or not isinstance(scopes, dict):
            continue
        for scope_id, facts in scopes.items():
            if isinstance(facts, dict):
                candidates.extend((key, fact, scope_type, scope_id) for key, fact in facts.items())
    arg_fields = {"product_advised": {"sku"}, "variant_sku": {"sku", "new_variant_sku"},
                  "price_quoted_vnd": {"price_vnd"}, "order_id": {"order_id"},
                  "payment": {"payment"}, "size": {"size"}, "color": {"color"},
                  "preferred_size": {"size"}, "preferred_color": {"color"}, "promo_code": {"promo_code"}}
    used = set()
    for key, fact, scope_type, scope_id in candidates:
        if not isinstance(fact, dict) or fact.get('status', 'active') != 'active':
            continue
        source = _source_session_id(fact.get("source") if isinstance(fact, dict) else None)
        if source is None or source == current_session_id:
            continue
        value = fact.get("value")
        if value is None:
            continue
        if customer_text:
            repeated = _speech_uses(customer_text, key, value, scope_type, scope_id, customer=True, catalog_calls=catalog)
            folded_customer = _fold(customer_text)
            scope_mentioned = bool(re.search(r"\bphong\b|\broom\b|" + "|".join(
                _literal_pattern(alias) for aliases in _ROOM_ALIASES.values() for alias in aliases), folded_customer)) if scope_type == "room" else bool(re.search(r"(?<![\w-])sku-[\w-]+", folded_customer))
            if repeated or (scope_id is not None and not scope_mentioned and
                    _speech_uses(customer_text, key, value, None, None, customer=True, catalog_calls=catalog)):
                continue
        spoken = _speech_uses(agent_text, key, value, scope_type, scope_id, catalog_calls=catalog)
        passed = any(
            _argument_uses_fact(call, key, value, scope_type, scope_id, arg_fields.get(key, {key}),
                               catalog, (scoped_facts or {}).get('room', {}), customer_text)
            for call in tool_calls if isinstance(call.get('result'), dict) and
                'error' not in call['result'] and call['result'].get('ok') is not False and call['result'].get('success') is not False)
        if spoken or passed:
            used.add(key)
            if usage_evidence is not None:
                evidence = {'field': key, 'scope_type': scope_type or 'global',
                            'via': (['speech'] if spoken else []) + (['tool_args'] if passed else [])}
                if evidence not in usage_evidence:
                    usage_evidence.append(evidence)
    return sorted(used)


def public_memory_writes(call: str, turn: int, memory_writes: list[dict], *, customer_name: str | None = None) -> list[dict]:
    sensitive = {"name", "customer_name", "phone", "customer_phone", "address", "shipping_address",
                 "bank_account", "account_number", "cccd", "national_id"}
    fields = {"key","value","op","customer_id","evidence_quote","scope_type","scope_id"}
    names = {customer_name} if customer_name else set()
    result = []
    for item in memory_writes:
        if not isinstance(item,dict):
            continue
        value = {key:_safe_value(v,("memory_writes",key)) for key,v in item.items() if key in fields}
        if item.get("key") in sensitive:
            if isinstance(item.get("value"),str):
                names.add(item["value"])
            value["value"] = "[TÊN ĐÃ ẨN]" if item["key"] in {"name","customer_name"} else "[PII ĐÃ ẨN]"
        value["source"] = f"{call}#turn{turn}"
        result.append(value)
    return _mask_names(result,names)


def trace_line(run_id: str, config: str, scenario_id: str, call: str, turn: int,
               customer_text: str, agent_text: str, tool_calls: list[dict],
               memory_writes: list[dict], used_facts: list[str],
               total_ms: float, call_brief_latency_ms: float | None,
               input_mode: str, customer_name: str | None = None, *,
               safety_issues: list | None = None, call_spec: dict | None = None) -> dict[str, Any]:
    raw_row = {"scenario_id": scenario_id, "call": call, "turn": turn,
               "agent_text": agent_text, "tool_calls": deepcopy(tool_calls),
               "memory_writes": deepcopy(memory_writes)}
    names = {customer_name} if customer_name else set()
    names.update(value for tool in tool_calls
                 for key, value in (tool.get("args") or {}).items()
                 if key == "customer_name" and isinstance(value, str))
    names.update(t.get("result",{}).get("name") for t in tool_calls
                 if isinstance(t.get("result"),dict) and isinstance(t["result"].get("name"),str))
    names.update(item.get("value") for item in memory_writes
                 if isinstance(item, dict) and item.get("key") in {"customer_name", "name"}
                 and isinstance(item.get("value"), str))
    for name in sorted(names, key=len, reverse=True):
        if name and len(name) > 1:
            pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)
            customer_text = pattern.sub("[TÊN ĐÃ ẨN]", customer_text)
            agent_text = pattern.sub("[TÊN ĐÃ ẨN]", agent_text)
            memory_writes = [{**item, "evidence_quote": pattern.sub(
                "[TÊN ĐÃ ẨN]", item["evidence_quote"])}
                if isinstance(item, dict) and isinstance(item.get("evidence_quote"), str)
                else item for item in memory_writes]
    public_writes = public_memory_writes(call, turn, memory_writes, customer_name=customer_name)
    safe_calls = _safe_tool_calls(tool_calls)
    customer_text = mask_pii(customer_text)
    agent_text = mask_pii(agent_text)
    row = build_trace_row(scenario_id, call, turn, customer_text, agent_text,
                          safe_calls, public_writes, used_facts, total_ms,
                          call_brief_latency_ms)
    if safety_issues is not None:
        from eval_harness.trace_evidence import inspect_redaction
        safety_issues.extend(inspect_redaction(raw_row, row, call_spec=call_spec or {}))
    row["run_id"] = run_id
    row["config"] = config
    row["customer_text"] = customer_text
    row["customer_input_mode"] = input_mode
    row["latency"] = {"ttft_ms": int(total_ms), "total_ms": int(total_ms)}
    if call_brief_latency_ms is not None:
        row["call_brief_latency_ms"] = int(call_brief_latency_ms)
    return row


def write_jsonl(trace: dict[tuple[str, str], list[dict]], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    import os
    fd, temporary = tempfile.mkstemp(prefix=".trace-", dir=target.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for rows in trace.values():
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    Path(temporary).replace(target)
