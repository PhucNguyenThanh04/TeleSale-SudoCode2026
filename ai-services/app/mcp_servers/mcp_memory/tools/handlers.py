"""Thin memory MCP handlers."""

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError

from app.mcp_servers.mcp_memory.schemas import ReadInput, WriteInput, TurnStatusInput
from app.mcp_servers.mcp_memory.services.memory import read, write
from app.mcp_servers.mcp_memory.services.turn_status import read_turn_status
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict) -> dict:
    return await trace_mcp_call("memory", name, args, lambda: _invoke(repo, name, args))


async def _invoke(repo, name: str, args: dict) -> dict:
    try:
        if name == "memory.turn_status":
            payload = TurnStatusInput.model_validate(args).model_dump(mode="json")
            return await read_turn_status(repo, **payload)
        if name == "memory.read":
            payload = ReadInput.model_validate(args).model_dump(mode="json")
            projector = LangMemProjection(repo.dsn) if hasattr(repo, "dsn") else None
            return await read(repo, **payload, projector=projector)
        if name == "memory.write":
            payload = WriteInput.model_validate(args).model_dump(mode="json")
            return await write(repo, **payload)
    except ValidationError as exc:
        log_mcp_validation("memory", name, exc)
        return {"error": "invalid_args"}
    except Exception as exc:
        log_mcp_exception("memory", name, exc)
        return {"error": "tool_unavailable"}
    return {"error": "unknown_tool"}


def create_server(repo, token: str | None = None) -> FastMCP:
    auth = StaticTokenVerifier({token: {"client_id": "harness", "scopes": ["tools"]}}) if token else None
    mcp = FastMCP("telesale-memory", auth=auth)

    @mcp.tool(name="eval.database_identity")
    async def eval_database_identity() -> dict:
        return await repo.database_identity()

    @mcp.tool(name="memory.read")
    async def memory_read(customer_id: str | None, session_id: str,
                          max_episodes: int = 5, include_prior: bool = True) -> dict:
        return await invoke(repo, "memory.read", locals())

    @mcp.tool(name="memory.write")
    async def memory_write(action: str, customer_id: str | None, session_id: str,
                           data: dict, operation_key: str | None = None) -> dict:
        return await invoke(repo, "memory.write", locals())

    @mcp.tool(name="memory.turn_status")
    async def memory_turn_status(customer_id: str | None, session_id: str,
                                 client_msg_id: str) -> dict:
        return await invoke(repo, "memory.turn_status", locals())

    return mcp
