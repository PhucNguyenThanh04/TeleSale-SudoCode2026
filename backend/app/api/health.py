from fastapi import APIRouter

from app.configs import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "env": settings.app_env}
