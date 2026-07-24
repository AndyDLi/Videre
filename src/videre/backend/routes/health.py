"""
Liveness/readiness endpoint.
"""

import logging

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import RedisDependency, SessionDependency

logger = logging.getLogger("videre.backend.health")

router = APIRouter(tags=["health"])


async def _postgres_reachable(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as error:
        logger.warning("postgres unreachable", extra={"error": str(error)})
        return False


async def _redis_reachable(redis_client: Redis) -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception as error:
        logger.warning("redis unreachable", extra={"error": str(error)})
        return False


@router.get("/healthz")
async def healthz(session: SessionDependency, redis_client: RedisDependency, response: Response) -> dict[str, object]:
    check = {
        "postgres": await _postgres_reachable(session),
        "redis": await _redis_reachable(redis_client),
    }
    healthy = all(check.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "healthy" if healthy else "degraded", "checks": check}
