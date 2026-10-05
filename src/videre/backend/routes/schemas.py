"""
Public response shapes.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GpuResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    node_id: str
    utilization_percentage: float
    temperature_celsius: float
    memory_used_mb: int
    memory_total_mb: int
    ecc_correctable_count: int
    ecc_uncorrectable_count: int
    xid_error_count: int
    health_state: str
    last_updated_at: datetime


class NodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    cluster_id: str
    cpu_cores: int
    memory_gb: int
    gpu_count: int
    health_state: str
    updated_at: datetime


class NodeDetailResponse(NodeResponse):
    gpus: list[GpuResponse] = []


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    cluster_id: str
    lifecycle_state: str
    requested_cpu_cores: int
    requested_memory_gb: int
    requested_gpu_count: int
    priority: int
    pod_name: str | None
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class JobDetailResponse(JobResponse):
    assigned_node_ids: list[str] = []


class FailureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    entity_type: str
    entity_id: str
    category: str
    root_cause_tag: str
    correlation_id: str
    detected_at: datetime
    resolved_at: datetime | None


class CapacityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    total_gpus: int
    unavailable_gpus: int = Field(description="GPU FAILED or node not READY; unavailable for new work.")
    degraded_gpus: int = Field(description="DEGRADED or THROTTLING GPUs on READY nodes.")
    idle_gpus: int = Field(description="HEALTHY GPUs on READY nodes with utilization below 5%.")
    active_gpus: int = Field(description="HEALTHY GPUs on READY nodes with utilization at least 5%.")
    idle_reserved_gpus: int = Field(
        deprecated=True, description="Compatibility alias for idle_gpus; no reservation evidence.",
    )
    drained_node_count: int
    unschedulable_node_count: int
    queued_job_count: int
    queueing_delay_event_count: int = Field(description="Node-linked QUEUEING_DELAY records over the last 3 days.")
    fragmentation_event_count: int = Field(
        deprecated=True, description="Compatibility alias for queueing_delay_event_count.",
    )
