"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from .config import Settings, get_settings
from .db import create_db_engine, init_db
from .llm import LLMService
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lyftr")


def create_app(settings: Settings | None = None, *, llm: LLMService | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        logger.info(
            "startup: keys=%d cache=%s db=%s",
            len(settings.keys), settings.cache_enabled, settings.database_url,
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="Lyftr AI Chatbot",
        version="1.0.0",
        description="LLM chatbot with LiteLLM key failover and response caching.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.db_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.state.llm = llm or LLMService.from_settings(settings)

    @app.exception_handler(Exception)
    async def unhandled_exception(_request: Request, exc: Exception):  # noqa: ANN201
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.include_router(router)
    return app


app = create_app()
