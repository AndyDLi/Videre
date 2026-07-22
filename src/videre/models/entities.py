"""
Core entity models shared throughout Videre.
References use IDs rather than nested objects because entities are serialized as Kafka JSON and stored in PostgreSQL.
Cluster, nodes, and GPUs are created at simulator startup and never added or removed during a run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import GpuHealthState, JobState, NodeHealthState, SchedulerEventType


def _utc() -> datetime:
    return datetime.now(UTC)


class Cluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str
    name: str
    node_ids: list[str] = Field(default_factory=list)


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str
    cluster_id: str
    cpu_cores: int = Field(gt=0)
    memory_gb: int = Field(gt=0)
    gpu_count: int = Field(ge=0)
    health_state: NodeHealthState = NodeHealthState.READY


class GPU(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str
    node_id: str
    utilization_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    temperature_celsius: float = Field(default=0.0, ge=0.0)
    memory_used_mb: int = Field(default=0, ge=0)
    memory_total_mb: int = Field(gt=0)
    ecc_correctable_count: int = Field(default=0, ge=0)  # ECC single-bit correctable
    ecc_uncorrectable_count: int = Field(default=0, ge=0)  # ECC double-bit+ uncorrectable
    xid_error_count: int = Field(default=0, ge=0)  # NVIDIA GPU Xid errors
    health_state: GpuHealthState = GpuHealthState.HEALTHY
    
    @model_validator(mode="after")
    def _memory_used_must_be_within_total(self) -> GPU:
        if self.memory_used_mb > self.memory_total_mb:
            raise ValueError("memory_used_mb cannot exceed memory_total_mb")
        return self


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    cpu_cores: int = Field(gt=0)
    memory_gb: int = Field(gt=0)
    gpu_count: int = Field(ge=0)


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str
    cluster_id: str
    assigned_node_ids: list[str] = Field(default_factory=list)
    resources: ResourceRequest
    state: JobState = JobState.PENDING
    priority: int = 0
    pod_name: str | None = None
    last_checkpoint_time: datetime | None = None
    checkpoint_corrupt: bool = False
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SchedulerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str
    type: SchedulerEventType
    timestamp: datetime = Field(default_factory=_utc)
    job_id: str | None = None
    node_id: str | None = None
    delay_seconds: float | None = Field(default=None, ge=0.0)
    reason: str

    @model_validator(mode="after")
    def _delay_matches_type(self) -> SchedulerEvent:
        is_queueing_delay = self.type is SchedulerEventType.QUEUEING_DELAY
        if is_queueing_delay and self.delay_seconds is None:
            raise ValueError("delay_seconds is required for QUEUEING_DELAY events")
        if not is_queueing_delay and self.delay_seconds is not None:
            raise ValueError("delay_seconds is only valid for QUEUEING_DELAY events")
        return self
