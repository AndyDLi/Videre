"""
Redis read/write for cluster-health snapshots.
"""

from __future__ import annotations

from redis.asyncio import Redis

from .snapshot import CACHE_KEY_PREFIX, ClusterHealthSnapshot, cache_key


async def write_snapshot(redis_client: Redis, snapshot: ClusterHealthSnapshot, ttl_seconds: int) -> None:
    await redis_client.set(cache_key(snapshot.cluster_id), snapshot.model_dump_json(), ex=ttl_seconds)


async def read_snapshot(redis_client: Redis, cluster_id: str) -> ClusterHealthSnapshot | None:
    payload = await redis_client.get(cache_key(cluster_id))
    return None if payload is None else ClusterHealthSnapshot.model_validate_json(payload)


async def read_all_snapshots(redis_client: Redis) -> list[ClusterHealthSnapshot]:
    keys = sorted([key async for key in redis_client.scan_iter(match=f"{CACHE_KEY_PREFIX}:*")])
    if not keys:
        return []
    
    payloads = await redis_client.mget(keys)
    return [ClusterHealthSnapshot.model_validate_json(payload) for payload in payloads if payload is not None]
