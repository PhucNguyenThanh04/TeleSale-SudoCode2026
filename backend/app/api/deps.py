"""Authentication dependencies for protected FastAPI routes."""

from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError

from app.services.auth_service import decode_token


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """Return the authenticated user ID from a valid Bearer access token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return decode_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token không hợp lệ hoặc đã hết hạn",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


def get_ai_http(request: Request) -> httpx.AsyncClient:
    """Reuse the AsyncClient owned by FastAPI lifespan."""
    return request.app.state.ai_http
