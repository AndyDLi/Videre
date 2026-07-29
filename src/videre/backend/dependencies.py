"""
Shared connections, created once per process and injected into request handlers.
"""

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import Depends, Request
from httpx2 import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .ai.gemini import GeminiAnalyst
from .settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create and configure a reusable SQLAlchemy async DB connection pool."""
    
    return create_async_engine(settings.postgres_dsn, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_redis_client(settings: Settings) -> Redis:
    """Create and configure a reusable Redis client."""
    
    return Redis.from_url(settings.redis_url, decode_responses=True)


def create_http_client(settings: Settings) -> AsyncClient:
    """Create and configure a reusable HTTP client for Prometheus and Loki query APIs."""
    
    return AsyncClient(timeout=settings.ai_source_timeout_seconds)


def create_gemini_analyst(settings: Settings) -> GeminiAnalyst | None:
    if not settings.gemini_api_key.get_secret_value():
        return None
    return GeminiAnalyst(settings)


async def get_session(request: Request) -> AsyncIterable[AsyncSession]:
    """Dependency generator that yields a SQLAlchemy async session for a request handler."""
    
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_redis(request: Request) -> Redis:
    redis_client: Redis = request.app.state.redis_client
    return redis_client


def get_http_client(request: Request) -> AsyncClient:
    http_client: AsyncClient = request.app.state.http_client
    return http_client


def get_gemini_analyst(request: Request) -> GeminiAnalyst | None:
    analyst: GeminiAnalyst | None = request.app.state.gemini_analyst
    return analyst


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return session_factory


# type aliases for FastAPI to resolve dependencies in request handlers
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
RedisDependency = Annotated[Redis, Depends(get_redis)]
HttpClientDependency = Annotated[AsyncClient, Depends(get_http_client)]
GeminiAnalystDependency = Annotated["GeminiAnalyst | None", Depends(get_gemini_analyst)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
SessionFactoryDependency = Annotated["async_sessionmaker[AsyncSession]", Depends(get_session_factory)]
