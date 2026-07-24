"""
Shared connections, created once per process and injected into request handlers.
"""

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create and configure a reusable SQLAlchemy async DB connection pool."""
    
    return create_async_engine(settings.postgres_dsn, pool_size=5, max_overflow=5, pool_pre_ping=True)


def create_redis_client(settings: Settings) -> Redis:
    """Create and configure a reusable Redis client."""
    
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def get_session(request: Request) -> AsyncIterable[AsyncSession]:
    """Dependency generator that yields a SQLAlchemy async session for a request handler."""
    
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_redis(request: Request) -> Redis:
    redis_client: Redis = request.app.state.redis_client
    return redis_client


# type aliases for FastAPI to resolve dependencies in request handlers
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
RedisDependency = Annotated[Redis, Depends(get_redis)]
