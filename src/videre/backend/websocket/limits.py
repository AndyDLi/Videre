"""
Per-IP WebSocket connection cap, tracked in Redis.
"""

from __future__ import annotations

from redis.asyncio import Redis

CONNECTION_KEY_PREFIX = "ratelimit:websocket"
CONNECTION_KEY_TTL_SECONDS = 3600


def connection_key(client_ip: str) -> str:
    return f"{CONNECTION_KEY_PREFIX}:{client_ip}"


async def try_acquire(redis_client: Redis, client_ip: str, maximum_connections: int) -> bool:
    key = connection_key(client_ip)
    count = await redis_client.incr(key)
    await redis_client.expire(key, CONNECTION_KEY_TTL_SECONDS)
    if count > maximum_connections:
        await redis_client.decr(key)    # give the slot back by refusing the connection
        return False
    return True


async def release(redis_client: Redis, client_ip: str) -> None:
    key = connection_key(client_ip)
    if await redis_client.decr(key) < 0:
        await redis_client.set(key, 0)
