"""
Cluster summaries, served from the Redis snapshot cache.
Cached because cluster health is expensive to compute due to aggregates and no parameters.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..cache.snapshot import ClusterHealthSnapshot
from ..cache.store import read_all_snapshots, read_snapshot
from ..dependencies import RedisDependency

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("", response_model=list[ClusterHealthSnapshot])
async def list_clusters(redis_client: RedisDependency) -> list[ClusterHealthSnapshot]:
    snapshots = await read_all_snapshots(redis_client)
    if not snapshots:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="cluster health cache is empty"
        )
    return snapshots


@router.get("/{cluster_id}", response_model=ClusterHealthSnapshot)
async def get_cluster(cluster_id: str, redis_client: RedisDependency) -> ClusterHealthSnapshot:
    snapshot = await read_snapshot(redis_client, cluster_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cluster not found")
    return snapshot
