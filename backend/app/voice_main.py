"""Standalone demo entrypoint: uvicorn app.voice_main:app --app-dir backend."""

from contextlib import asynccontextmanager
from pathlib import Path
import os

import asyncpg
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.voice import router
from app.api.text import router as text_router
from app.api.knowledge import router as knowledge_router
from app.auth import router as auth_router
from app.configs import VoiceSettings
from app.database.demo_users import DemoUsers, postgres_url
from app.services.voice_speech import SpeechClient


def create_app(settings: VoiceSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or VoiceSettings()
        pool = None
        if config.database_url:
            pool = await asyncpg.create_pool(postgres_url(config.database_url), min_size=1, max_size=5)
            if os.getenv('SYSTEM_BOOT_ID'):
                try:
                    async with pool.acquire() as conn:
                        boot = await conn.fetchrow('SELECT boot_id,status FROM system_boot.current WHERE singleton')
                    if not boot or boot['boot_id'] != os.environ['SYSTEM_BOOT_ID'] or boot['status'] != 'ready':
                        raise RuntimeError('Managed system boot is not ready or has been replaced')
                except BaseException:
                    await pool.close()
                    raise
        headers = ({"X-AI-Internal-Token": config.ai_internal_token.get_secret_value()}
                   if config.ai_internal_token else {})
        async with httpx.AsyncClient(
            base_url=config.ai_service_url, headers=headers,
            timeout=httpx.Timeout(config.ai_service_timeout_seconds),
        ) as ai_http, httpx.AsyncClient(
            base_url=config.speech_http_url,
            timeout=httpx.Timeout(config.speech_timeout_seconds,
                                  connect=config.speech_connect_timeout_seconds),
        ) as speech_http:
            app.state.voice_settings = config
            app.state.demo_users = DemoUsers(pool) if pool else None
            app.state.ai_http = ai_http
            app.state.voice_speech = SpeechClient(
                config.speech_listen_url, speech_http, config.speech_voice,
                config.speech_connect_timeout_seconds,
            )
            try:
                yield
            finally:
                if pool:
                    await pool.close()
                del app.state.demo_users
                del app.state.voice_speech
                del app.state.ai_http
                del app.state.voice_settings

    app = FastAPI(title="TeleSale Voice Demo Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(text_router)
    app.include_router(knowledge_router)
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    app.mount("/assets", StaticFiles(directory=frontend), name="voice-assets")

    @app.get('/login', include_in_schema=False)
    async def login_site():
        return FileResponse(frontend / 'login.html')

    @app.get("/", include_in_schema=False)
    async def voice_site():
        return FileResponse(frontend / "index.html")

    @app.get('/chat', include_in_schema=False)
    async def text_site():
        return FileResponse(frontend / 'chat.html')

    @app.get('/knowledge', include_in_schema=False)
    async def knowledge_site():
        return FileResponse(frontend / 'knowledge.html')

    return app


app = create_app()
