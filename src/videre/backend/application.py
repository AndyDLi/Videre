"""
FastAPI application factory.
Lifespan manages long-lived resources: database connections and Redis cache.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from videre.logging_config import configure_logging

from .dependencies import create_engine, create_redis_client
from .persistence.consumer import run_consumer
from .persistence.retention import run_retention_pruning
from .routes import health
from .settings import Settings

logger = logging.getLogger("videre.backend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    
    # connects to the databases
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.redis_client = create_redis_client(settings)
    
    # Kafka persistence and retention pruning run in the background
    app.state.background_tasks = [
        asyncio.create_task(run_consumer(app.state.session_factory, settings)),
        asyncio.create_task(run_retention_pruning(app.state.session_factory)),
    ]
    
    logger.info("backend started")

    try:
        yield
    finally:
        for task in app.state.background_tasks:
            task.cancel()
        await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
        await app.state.redis_client.aclose()
        await engine.dispose()
        logger.info("backend stopped")


def create_application(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    application = FastAPI(title="Videre", lifespan=lifespan)
    application.state.settings = settings if settings is not None else Settings()
    application.include_router(health.router)
    return application
