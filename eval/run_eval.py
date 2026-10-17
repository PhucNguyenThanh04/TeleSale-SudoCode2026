"""Run BTC conversations through the production harness and emit real traces."""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-services"))

from jsonschema import Draft202012Validator  # noqa: E402

from app.agent.factory import build_runtime  # noqa: E402
from app.agent.guardrails.checks import _money_claims, mask_pii, safe_tool_result  # noqa: E402
from app.configs import get_settings  # noqa: E402
from app.schemas.agent import TextTurnRequest  # noqa: E402
from app.schemas.trace import AgentTraceLine  # noqa: E402
from eval.catalog_search_benchmark import catalog_search_metrics  # noqa: E402


async def _require_eval_database(runtime, isolated_db: bool) -> None:
    """Fail before the first turn unless all three MCP pools reach one allowed eval DB."""
    if not isolated_db:
        raise ValueError("Pass --isolated-db after configuring a dedicated eval database")
    allowed = {name.strip() for name in os.getenv("EVAL_DB_ALLOWLIST", "telesale_eval").split(",")}
    allowed.discard("")
    allowed = {name for name in allowed if re.fullmatch(r"[a-z][a-z0-9_]*", name)
               and re.search(r"(^|_)eval($|_)", name)}
    if not allowed:
        raise ValueError("EVAL_DB_ALLOWLIST must contain an eval-named database")
    probe = getattr(getattr(runtime, "tools", None), "database_identity", None)
    if not callable(probe):
        raise RuntimeError("Eval database identity probe is unavailable")
    identities = []
    for service in ("catalog", "order", "memory"):
        identity = await probe(service)
        if not isinstance(identity, dict) or identity.get("error"):
            raise RuntimeError(f"Cannot verify {service} MCP database identity")
        name = identity.get("database")
        if name not in allowed:
            raise RuntimeError(f"{service} MCP database is not in the eval allowlist")
        endpoint = tuple(identity.get(key) for key in
                         ("host", "port", "server_address", "server_port"))
        if (not isinstance(endpoint[0], str) or not endpoint[0]
                or type(endpoint[1]) is not int
                or not isinstance(endpoint[2], str) or not endpoint[2]
                or type(endpoint[3]) is not int):
            raise RuntimeError(f"{service} MCP database host is unverified")
        identities.append((name, *endpoint))
    if len(set(identities)) != 1:
        raise RuntimeError("MCP services do not share one eval database endpoint")


def _scenario_inputs(folder: Path):
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        previous = date(2026, 10, 15)
        for call_name, call in scenario["calls"].items():
            on = (date.fromisoformat(call["call_date"]) if call.get("call_date")
                  else previous + timedelta(days=call.get("days_later", 0)))
            previous = on
            turns = call.get("customer_turns_asr") or call["customer_turns"]
            mode = call.get("input_mode", "asr_transcript" if call.get("customer_turns_asr")
                            else "clean")
            if mode not in {"clean", "asr_transcript", "chat_teencode"}:
                mode = "clean"
            channel = call.get("channel", "hotline")
            identity = call.get("channel_identity") or (scenario.get("customer_phone")
                                                       if channel == "hotline" else None)
            yield scenario["scenario_id"], call_name, on, channel, identity, mode, turns


def _questions(answer: str) -> list[dict]:
    result = []
    for part in re.split(r"(?<=[?])", answer):
        if "?" not in part:
            continue
        lower = part.casefold()
        slot = next((key for key, pattern in (
            ("room_area_m2", r"diện tích|bao nhiêu\s*(?:m2|m²|mét)|phòng.*mấy"),
            ("budget_vnd", r"ngân sách|muốn chi|tầm giá"),
            ("has_children", r"con nhỏ|em bé|trẻ nhỏ"),
            ("product_advised", r"mẫu nào|sản phẩm nào|máy nào|giày nào"),
            ("size", r"size|cỡ giày"),
            ("color", r"màu"),
            ("payment", r"thanh toán|cod|chuyển khoản"),
            ("blocker", r"băn khoăn|cân nhắc|ngại"),
        ) if re.search(pattern, lower)), None)
        if slot:
            result.append({"slot": slot, "type": "confirm" if
                           re.search(r"đúng không|vẫn|phải không|còn.*không", lower)
                           else "open", "text": part.strip()})
    return result


def _claims(answer: str, calls: list[dict]) -> list[dict]:
    claims = []
    for clause in re.split(r"\.(?!\d)|[!?;\n]", answer):
        if not clause.strip():
            continue
        lower = clause.casefold()
        for amount, kind, negative in _money_claims(clause):
            if (kind == "price" and amount >= 100_000
                    and re.search(r"giá|\bchỉ\b|\bcòn\b", lower)):
                claims.append({"field": "price_vnd", "value": amount, "text": clause.strip()})
        stock = re.search(r"\b(còn hàng|có hàng|sẵn hàng|hết hàng)\b", lower)
        if stock:
            claims.append({"field": "in_stock", "value": stock.group(1) != "hết hàng",
                           "text": clause.strip()})
        promo = re.search(r"\b(?:khuyến mãi|giảm giá|ưu đãi)\b", lower)
        if promo:
            inactive = bool(re.search(r"\b(?:hết|không còn|chưa có|không có)\s+"
                                      r"(?:(?:chương trình|mã)\s+)?"
                                      r"(?:khuyến mãi|giảm giá|ưu đãi)\b", lower))
            code = re.search(r"\b([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+)\b", clause)
            field = f"promo_{code.group(1)}_active" if code else "promo_active"
            claims.append({"field": field, "value": not inactive, "text": clause.strip()})
        for field, pattern in (
            ("delivery_days", r"giao\s+(?:trong|sau)\s+(\d+)\s+ngày"),
            ("return_days", r"(?:đổi|trả|đổi trả)\s+(?:trong\s+)?(\d+)\s+ngày"),
        ):
            match = re.search(pattern, lower)
            if match:
                claims.append({"field": field, "value": int(match.group(1)),
                               "text": clause.strip()})
    return claims


def _facts_used(answer: str, state: dict) -> list[str]:
    profile = state.get("profile", {})
    evidence = answer.casefold() + " " + json.dumps(
        [{"name": call.get("name"), "args": call.get("args", {})}
         for call in state.get("tool_calls", [])], ensure_ascii=False).casefold()
    used = []
    for key, fact in profile.items():
        if not isinstance(fact, dict) or not fact.get("source"):
            continue
        source_session = fact["source"].split(":", 1)[0]
        if source_session == str(state["request"].session_id):
            continue
        value = fact.get("value")
        if value is not None and str(value).casefold() in evidence:
            used.append(key)
    return sorted(used)


def _trace_args(args: dict) -> dict:
    """Preserve business arguments while excluding raw contact and address fields."""
    return {key: mask_pii(value) if isinstance(value, str) else value
            for key, value in args.items()
            if key not in {"address", "brief", "source_identity", "verified_customer_id"}}


async def run(args, runtime=None) -> int:
    schema_path = args.scenarios.resolve().parents[1] / "schemas" / "trace_log.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    if runtime is None:
        runtime = build_runtime(get_settings())
    await _require_eval_database(runtime, args.isolated_db)
    runtime.memory.include_prior = args.config == "full"
    run_id = str(uuid4())
    rows = []
    events = []
    for scenario_id, call_name, on, channel, identity, mode, turns in _scenario_inputs(args.scenarios):
        session_id = uuid4()
        for turn_no, customer_text in enumerate(turns, 1):
            request = TextTurnRequest(client_msg_id=uuid4(), session_id=session_id,
                                      channel=channel, channel_identity=identity,
                                      on=on, text=customer_text, input_mode=mode)
            started = time.perf_counter()
            response = await runtime.run(request)
            elapsed = round((time.perf_counter() - started) * 1000)
            state = runtime.state_for(request)
            if state is None:
                raise RuntimeError("Harness did not expose its real turn state")
            answer = mask_pii(response.agent_text)
            row = AgentTraceLine(
                run_id=run_id, config=args.config, scenario_id=scenario_id,
                call=call_name, turn=turn_no, customer_text=mask_pii(customer_text),
                agent_text=answer, questions=_questions(answer),
                claims=_claims(answer, state.get("tool_calls", [])),
                facts_used=_facts_used(answer, state),
                tool_calls=[{"name": call["name"], "args": _trace_args(call.get("args", {})),
                             "result": safe_tool_result(call.get("result", {}))}
                            for call in state.get("tool_calls", [])],
                latency={"ttft_ms": elapsed, "total_ms": elapsed},
                call_brief_latency_ms=(response.call_brief or {}).get("latency_ms"),
                memory_writes=state.get("memory_writes", []), customer_input_mode=mode,
            ).model_dump(mode="json")
            validator.validate(row)
            rows.append(row)
            checks = state.get("verifier_events", [])
            if checks:
                events.append({"scenario_id": scenario_id, "call": call_name,
                               "turn": turn_no, "checks": checks})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8")
    args.out.with_suffix(".events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_out = getattr(args, "report_out", None) or args.out.with_suffix(".report.json")
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps({
        "run_id": run_id, "config": args.config,
        "catalog_search": catalog_search_metrics(rows),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--config", required=True, choices=("full", "baseline_no_memory"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report-out", type=Path,
                        help="JSON report path (default: trace path with .report.json suffix)")
    parser.add_argument("--isolated-db", action="store_true",
                        help="Confirm MCP servers use a dedicated, freshly seeded eval DB")
    args = parser.parse_args()
    print(f"Wrote {asyncio.run(run(args))} real turns to {args.out}")
