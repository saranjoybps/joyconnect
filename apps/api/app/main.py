from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.llm import LLM, OpenAIChat
from app.agent.runtime import AgentRuntime
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.logging import setup_logging
from app.core.secrets import SecretStore, build_secret_store
from app.db.client import Database, SupabaseRestDatabase
from app.oauth import router as oauth_router
from app.routers import approvals, chat, connections, health


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    secret_store: SecretStore | None = None,
    http: httpx.AsyncClient | None = None,
    llm: LLM | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        own_http = http is None
        app.state.http = http or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        app.state.db = db or SupabaseRestDatabase(
            settings.supabase_url, settings.supabase_service_role_key, app.state.http
        )
        app.state.secret_store = secret_store or build_secret_store(
            settings.secret_store, app.state.db, settings.token_encryption_key
        )
        app.state.chat_limiter = SlidingWindowLimiter()
        llm_holder: list[LLM] = [llm] if llm else []

        def llm_factory() -> LLM:
            if not llm_holder:
                llm_holder.append(OpenAIChat(settings))  # raises LLMError if not configured
            return llm_holder[0]

        app.state.runtime = AgentRuntime(app.state.db, app.state.secret_store, app.state.http, settings, llm_factory)
        yield
        if own_http:
            await app.state.http.aclose()

    app = FastAPI(title="Connect API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_base_url],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    if settings is not get_settings():
        app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(health.router)
    app.include_router(connections.router)
    app.include_router(oauth_router.router)
    app.include_router(chat.router)
    app.include_router(approvals.router)
    return app


app = create_app()
