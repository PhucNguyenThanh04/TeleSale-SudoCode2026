"""Measure catalog.search calls per independent turn with the configured real model.

Only catalog.search is available to this benchmark. Memory stays in process, so
MCP mode reads the deployed catalog without writing evaluation turns or orders.
"""

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-services"))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402

from app.agent.harness.runtime import AgentHarnessRuntime  # noqa: E402
from app.agent.mcp.gateway import MCPGateway  # noqa: E402
from app.configs import get_settings  # noqa: E402
from app.infarstructure.llm import build_llm  # noqa: E402
from app.mcp_servers.mcp_shared.commerce_rules import _catalog  # noqa: E402
from app.schemas.agent import TextTurnRequest  # noqa: E402


def catalog_search_metrics(rows: list[dict]) -> dict:
    """Summarize actual recorded tool calls, including turns with no search."""
    counts = [sum(call.get("name") == "catalog.search"
                  for call in row.get("tool_calls", [])) for row in rows]
    search_turns = sum(count > 0 for count in counts)
    one_search = sum(count == 1 for count in counts)
    return {
        "turns": len(counts),
        "search_turns": search_turns,
        "one_search_turns": one_search,
        "one_search_rate_among_search_turns": (
            round(one_search / search_turns, 3) if search_turns else None),
        "total_calls": sum(counts),
        "mean_calls_per_turn": round(statistics.mean(counts), 3) if counts else None,
        "calls_per_turn": counts,
    }


class _ModelCalls(BaseCallbackHandler):
    def __init__(self) -> None:
        self.count = 0

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self.count += 1


class _TurnMemory:
    """Enough memory contract for independent single-turn benchmark sessions."""

    include_prior = False

    async def read_context(self, session_id, customer_id):
        return {"history": [], "profile": {}, "episodes": [],
                "owned_order_ids": [], "turn_count": 0}

    async def claim_pending(self, session_id, customer_id, client_msg_id):
        return {"memory_writes": []}

    async def commit_turn(self, session_id, customer_id, customer_text, agent_text,
                          on, channel, client_msg_id, facts, orders=None):
        return {"turn_no": 1, "memory_writes": []}


class _CatalogOnlyGateway:
    def __init__(self, source: str, products: list[dict] | None,
                 remote: MCPGateway | None) -> None:
        self.source, self.products, self.remote = source, products, remote

    async def invoke(self, name: str, args: dict) -> dict:
        return await self.invoke_trusted(name, args, None)

    async def invoke_trusted(self, name: str, args: dict, customer_id,
                             channel=None, channel_identity=None,
                             operation_key=None) -> dict:
        if name != "catalog.search":
            return {"error": "benchmark_tool_unavailable"}
        if self.source == "adapter":
            return _catalog(self.products, args)
        return await self.remote.invoke_trusted(name, args, customer_id,
                                                channel, channel_identity,
                                                operation_key)


async def measure(args: argparse.Namespace) -> dict:
    if args.runs < 1:
        raise ValueError("--runs must be positive")
    business_date = date.fromisoformat(args.on)
    settings = get_settings()
    products = None
    remote = None
    if args.source == "adapter":
        data_dir = Path(args.data_dir or os.environ.get("BTC_DATA_DIR") or
                        ROOT.parent / "BTC-Data-Vong1-TEAMS")
        products = json.loads((data_dir / "catalog/products.json").read_text(
            encoding="utf-8"))["products"]
    else:
        if not settings.mcp_catalog_url or not settings.mcp_internal_token:
            raise RuntimeError("MCP_CATALOG_URL and MCP_INTERNAL_TOKEN are required")
        remote = MCPGateway(settings.mcp_catalog_url, None, None,
                            settings.mcp_internal_token.get_secret_value())
    gateway = _CatalogOnlyGateway(args.source, products, remote)
    counter = _ModelCalls()
    model = build_llm(settings)
    model.callbacks = [counter]
    extraction_mode = args.fact_extraction_mode or settings.fact_extraction_mode
    runtime = AgentHarnessRuntime(
        model, gateway, _TurnMemory(),
        max_tool_calls=settings.agent_max_tool_calls,
        prompt_history_turns=settings.agent_prompt_history_turns,
        guardrails_enabled=settings.agent_guardrails_enabled,
        agent_kind=settings.agent_kind,
        fact_extraction_mode=extraction_mode,
    )
    turns = []
    for index in range(args.runs):
        request = TextTurnRequest(
            client_msg_id=uuid4(), session_id=uuid4(), channel="web_chat",
            channel_identity=None, on=business_date, text=args.text,
            input_mode="clean",
        )
        before = counter.count
        started = time.perf_counter()
        await runtime.run(request)
        state = runtime.state_for(request)
        if state is None:
            raise RuntimeError("Benchmark turn has no recorded state")
        searches = [call for call in state.get("tool_calls", [])
                    if call.get("name") == "catalog.search"]
        turns.append({
            "turn": index + 1,
            "tool_calls": [{"name": "catalog.search"} for _ in searches],
            "model_calls": counter.count - before,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "result_totals": [call.get("result", {}).get("total") for call in searches],
        })
    return {
        "source": args.source,
        "business_date": business_date.isoformat(),
        "input_sha256": hashlib.sha256(args.text.encode("utf-8")).hexdigest(),
        "model": settings.llm_model,
        "agent_kind": settings.agent_kind,
        "fact_extraction_mode": extraction_mode,
        "catalog_search": catalog_search_metrics(turns),
        "model_calls_total": sum(turn["model_calls"] for turn in turns),
        "elapsed_seconds_total": round(sum(turn["elapsed_seconds"] for turn in turns), 3),
        "turns": [{key: value for key, value in turn.items() if key != "tool_calls"}
                  for turn in turns],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="Synthetic customer question")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--on", default="2026-10-15")
    parser.add_argument("--source", choices=("adapter", "mcp"), default="mcp")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--fact-extraction-mode", choices=("off", "fallback", "always"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(measure(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("source", "catalog_search", "model_calls_total",
                       "elapsed_seconds_total")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
