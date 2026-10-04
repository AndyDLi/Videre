"""
FastAPI application factory.
Lifespan manages long-lived resources: database connections and Redis cache.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from videre.logging_config import configure_logging

from .cache.refresh import run_cache_refresh
from .dependencies import create_engine, create_gemini_analyst, create_http_client, create_redis_client
from .metrics import instrument_application
from .persistence.consumer import run_consumer
from .persistence.retention import run_retention_pruning
from .routes import ai, capacity, clusters, failures, health, jobs, nodes, stream
from .settings import Settings
from .websocket.manager import ConnectionManager

logger = logging.getLogger("videre.backend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    
    # connects to the databases
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.redis_client = create_redis_client(settings)
    app.state.http_client = create_http_client(settings)
    app.state.gemini_analyst = create_gemini_analyst(settings)
    
    # WebSocket connection manager; streaming/broadcast/fanout pattern
    app.state.connection_manager = ConnectionManager()
    async def broadcast_snapshot() -> None:
        payload = await stream.current_payload(app.state.redis_client)
        await app.state.connection_manager.broadcast(payload)
    
    # Kafka persistence, retention pruning, and cache refresh run in the background
    app.state.background_tasks = [
        asyncio.create_task(run_consumer(app.state.session_factory, settings)),
        asyncio.create_task(run_retention_pruning(app.state.session_factory)),
        asyncio.create_task(
            run_cache_refresh(
                app.state.session_factory,
                app.state.redis_client,
                settings.cache_refresh_interval_seconds,
                on_refresh=broadcast_snapshot
            )
        )
    ]
    
    logger.info("backend started", extra={"ai_assistant_enabled": app.state.gemini_analyst is not None})

    try:
        yield
    finally:
        for task in app.state.background_tasks:
            task.cancel()
        await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
        await app.state.connection_manager.shutdown()
        await app.state.redis_client.aclose()
        await app.state.http_client.aclose()
        await engine.dispose()
        logger.info("backend stopped")


def create_application(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    application = FastAPI(title="Videre", lifespan=lifespan)
    application.state.settings = settings if settings is not None else Settings()
    
    # CORS middleware configuration; allow only the origins specified in settings to access the API
    application.add_middleware(
        CORSMiddleware,
        allow_origins=application.state.settings.cors_allowed_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
    )
    
    # register all API routers
    for router in (
        health.router,
        clusters.router,
        nodes.router,
        jobs.router,
        failures.router,
        capacity.router,
        stream.router,
        ai.router
    ):
        application.include_router(router)
    
    instrument_application(application)
    return application
