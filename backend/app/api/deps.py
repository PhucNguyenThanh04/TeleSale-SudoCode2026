"""Authentication dependencies for protected FastAPI routes."""

from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.api.operator_session import operator_from_cookie
from app.database.redis_session import get_redis


async def get_current_user_id(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
) -> str:
    """Return the operator ID from a server-side, HttpOnly browser session."""
    operator_id = await operator_from_cookie(request, redis)
    if operator_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên truy cập chưa sẵn sàng hoặc đã hết hạn",
        )
    return operator_id


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


def get_ai_http(request: Request) -> httpx.AsyncClient:
    """Reuse the AsyncClient owned by FastAPI lifespan."""
    return request.app.state.ai_http
