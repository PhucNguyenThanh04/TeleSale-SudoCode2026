"""Local demo operator session stored server-side in Redis."""

import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from redis.asyncio import Redis

from app.configs import get_settings
from app.database.redis_session import get_redis


router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE_NAME = "telesale_operator_session"
SESSION_SECONDS = 24 * 60 * 60
VISITOR_SESSION_SECONDS = 30 * 24 * 60 * 60


def session_key(token: str) -> str:
    return "operator_session:" + hashlib.sha256(token.encode()).hexdigest()


async def operator_from_cookie(request: Request, redis: Redis) -> str | None:
    token = request.cookies.get(COOKIE_NAME, "")
    if len(token) != 64:
        return None
    return await redis.get(session_key(token))


@router.post("/local-session")
async def local_session(request: Request, response: Response,
                        redis: Redis = Depends(get_redis)) -> dict[str, str]:
    """Bootstrap the localhost demo UI without exposing an operator credential."""
    settings = get_settings()
    if (settings.app_env == "production" or request.client is None
            or request.client.host not in ("127.0.0.1", "::1")
            or request.url.hostname not in ("127.0.0.1", "localhost")):
        raise HTTPException(403, "Local demo session is unavailable")
    operator_id = await operator_from_cookie(request, redis)
    if operator_id is None:
        token = secrets.token_hex(32)
        operator_id = f"local-demo:{uuid4()}"
        await redis.set(session_key(token), operator_id, ex=SESSION_SECONDS)
        response.set_cookie(
            COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
            samesite="strict", secure=False, path="/api",
        )
    return {"status": "ready"}


@router.post("/visitor-session")
async def visitor_session(request: Request, response: Response,
                          redis: Redis = Depends(get_redis)) -> dict[str, str | bool]:
    """Anonymous web identity bound to this browser, never a verified CRM identity."""
    if (request.url.hostname != "telesale.ktoxz.id.vn"
            or request.client is None or request.client.host not in ("127.0.0.1", "::1")):
        raise HTTPException(403, "Public web session is unavailable")
    operator_id = await operator_from_cookie(request, redis)
    returning = bool(operator_id and operator_id.startswith("web-visitor:"))
    if not returning:
        token = secrets.token_hex(32)
        operator_id = f"web-visitor:{uuid4()}"
        await redis.set(session_key(token), operator_id, ex=VISITOR_SESSION_SECONDS)
        response.set_cookie(
            COOKIE_NAME, token, max_age=VISITOR_SESSION_SECONDS, httponly=True,
            samesite="lax", secure=True, path="/api",
        )
    else:
        await redis.expire(session_key(request.cookies[COOKIE_NAME]), VISITOR_SESSION_SECONDS)
    return {"status": "ready", "returning_browser": returning}
