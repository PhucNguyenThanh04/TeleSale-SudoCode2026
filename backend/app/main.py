from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
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


@app.get("/")
async def root():
    return {"message": "Welcome to the TeleSale-SudoCode2026 backend API!"}


def get_ai_http(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency for calls to the AI service."""
    return request.app.state.ai_http
    