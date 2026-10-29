from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.calls import router as calls_router
from app.api.health import router as health_router
from app.api.operator_session import router as operator_session_router
from app.api.reference import router as reference_router
from app.configs import get_settings
from app.database.pg_session import check_postgres, create_pg_engine, create_pg_sessionmaker
from app.database.redis_session import check_redis, create_redis_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_pg_engine(settings.database_url)
    redis = None
    try:
        await check_postgres(engine)
        redis = create_redis_client(settings.redis_url)
        await check_redis(redis)

        async with httpx.AsyncClient(
            base_url=settings.ai_service_url,
            timeout=httpx.Timeout(settings.ai_service_timeout_seconds),
            headers={"X-AI-Internal-Token": settings.ai_internal_token.get_secret_value()}
                    if settings.ai_internal_token else None,
        ) as ai_http:
            app.state.pg_engine = engine
            app.state.pg_sessionmaker = create_pg_sessionmaker(engine)
            app.state.redis = redis
            app.state.ai_http = ai_http
            try:
                yield
            finally:
                del app.state.ai_http
                del app.state.redis
                del app.state.pg_sessionmaker
                del app.state.pg_engine
    finally:
        if redis is not None:
            await redis.aclose()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="TeleSale-SudoCode2026 backend API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(operator_session_router)
app.include_router(calls_router)
app.include_router(reference_router)

# Serve the operator console from the same origin as the authenticated API.
_frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if _frontend_dir.is_dir():
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="operator-console")


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/app/", status_code=307)
