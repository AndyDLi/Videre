"""
Precomputed cluster-health summary served from Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

CACHE_KEY_PREFIX = "cache:cluster-health"


class ClusterHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    cluster_id: str
    cluster_name: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    nodes_by_health_state: dict[str, int] = Field(default_factory=dict)
    gpus_by_health_state: dict[str, int] = Field(default_factory=dict)
    jobs_by_lifecycle_state: dict[str, int] = Field(default_factory=dict)
    unresolved_failure_count: int = 0


def cache_key(cluster_id: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{cluster_id}"
