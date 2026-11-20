
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError

from app.mcp_servers.mcp_memory.schemas import (ReadInput, WriteInput, TurnStatusInput, TimelineInput,
                                                validate_read_response)
from app.mcp_servers.mcp_memory.services.memory import read, write
from app.mcp_servers.mcp_memory.services.turn_status import read_turn_status
from app.mcp_servers.mcp_memory.services.timeline import read_timeline
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict) -> dict:
    return await trace_mcp_call("memory", name, args, lambda: _invoke(repo, name, args))


async def _invoke(repo, name: str, args: dict) -> dict:
    try:
        if name == "memory.timeline":
            payload = TimelineInput.model_validate(args).model_dump(mode='json')
            projector = LangMemProjection(repo.dsn) if hasattr(repo, 'dsn') else None
            return await read_timeline(repo, **payload, projector=projector)
        if name == "memory.turn_status":
            payload = TurnStatusInput.model_validate(args).model_dump(mode="json")
            return await read_turn_status(repo, **payload)
        if name == "memory.read":
            payload = ReadInput.model_validate(args).model_dump(mode="json")
            projector = LangMemProjection(repo.dsn) if hasattr(repo, "dsn") else None
            return validate_read_response(await read(repo, **payload, projector=projector))
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
                          max_episodes: int = 5, include_prior: bool = True,
                          query: str = "") -> dict:
        return await invoke(repo, "memory.read", locals())

    @mcp.tool(name="memory.write")
    async def memory_write(action: str, customer_id: str | None, session_id: str,
                           data: dict, operation_key: str | None = None) -> dict:
        return await invoke(repo, "memory.write", locals())

    @mcp.tool(name="memory.turn_status")
    async def memory_turn_status(customer_id: str | None, session_id: str,
                                 client_msg_id: str) -> dict:
        return await invoke(repo, "memory.turn_status", locals())

    @mcp.tool(name="memory.timeline")
    async def memory_timeline(customer_id: str | None, session_id: str, on: str,
                              offset: int = 0, limit: int = 10,
                              crm_sessions: list[dict] | None = None) -> dict:
        return await invoke(repo, 'memory.timeline', {'customer_id': customer_id, 'session_id': session_id,
            'on': on, 'offset': offset, 'limit': limit, 'crm_sessions': crm_sessions or []})

    return mcp
