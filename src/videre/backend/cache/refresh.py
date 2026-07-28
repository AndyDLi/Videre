"""
Periodic cluster-health cache refresh, ran as a background task.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..metrics import record_cluster_snapshots
from .builder import build_all_snapshots
from .store import write_snapshot

logger = logging.getLogger("videre.backend.cache")

TTL_MULTIPLIER = 4    # longer than the refresh interval to avoid cache misses if delays occur


async def refresh_once(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    interval_seconds: float
) -> int:
    async with session_factory() as session:
        snapshots = await build_all_snapshots(session)
    
    ttl_seconds = max(1, int(interval_seconds * TTL_MULTIPLIER))
    for snapshot in snapshots:
        await write_snapshot(redis_client, snapshot, ttl_seconds)    # write to Redis cache
    
    record_cluster_snapshots(snapshots)    # write to Prometheus registry
    return len(snapshots)


async def run_cache_refresh(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    interval_seconds: float,
    on_refresh: Callable[[], Awaitable[None]] | None = None
) -> None:
    while True:
        try:
            await refresh_once(session_factory, redis_client, interval_seconds)
            if on_refresh is not None:    # push the new snapshot to WebSocket clients
                await on_refresh()
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("cache refresh stopped")
            raise
        except Exception as error:
            logger.error("cache refresh failed", extra={"error": error})
            await asyncio.sleep(interval_seconds)
