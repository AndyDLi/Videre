"""
Combined failure context assembled from Postgres, Prometheus, and Loki.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from videre.database.tables import FailureEntityTable


class FailureRecordContext(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: str
    entity_type: str
    entity_id: str
    category: str
    root_cause_tag: str
    correlation_id: str
    detected_at: datetime
    resolved_at: datetime | None


class SchedulerEventContext(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    type: str
    timestamp: datetime
    related_job_id: str | None
    related_node_id: str | None
    delay_seconds: float | None
    reason: str


class NodeStateContext(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: str
    cluster_id: str
    health_state: str
    cpu_cores: int
    memory_gb: int
    gpu_count: int
    updated_at: datetime


class GpuStateContext(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    
    id: str
    node_id: str
    health_state: str
    utilization_percentage: float
    temperature_celsius: float
    memory_used_mb: int
    memory_total_mb: int
    ecc_correctable_count: int
    ecc_uncorrectable_count: int
    xid_error_count: int
    last_updated_at: datetime


class JobStateContext(BaseModel):
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
    assigned_node_ids: list[str] = []
    started_at: datetime | None
    completed_at: datetime | None


class PostgresContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    node: NodeStateContext | None = None
    gpus: list[GpuStateContext] = []
    job: JobStateContext | None = None
    unresolved_failures: list[FailureRecordContext] = []
    recently_resolved_failures: list[FailureRecordContext] = []
    scheduler_events: list[SchedulerEventContext] = []


class MetricSeriesContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    metric: str
    labels: dict[str, str]
    latest: float
    minimum: float
    maximum: float
    average: float
    sample_count: int


class PrometheusContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    window_minutes: int
    series: list[MetricSeriesContext] = []


class LogLineContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    timestamp: datetime
    labels: dict[str, str]
    line: str


class LokiContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    queries: list[str]
    window_minutes: int
    lines: list[LogLineContext] = []


class FailureContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    entity_type: FailureEntityTable
    entity_id: str
    generated_at: datetime
    postgres: PostgresContext | None = None
    prometheus: PrometheusContext | None = None
    logs: LokiContext | None = None
    
    @property
    def degraded_sources(self) -> list[str]:
        return [
            name
            for name, section in (
                ("postgres", self.postgres),
                ("prometheus", self.prometheus),
                ("logs", self.logs),
            )
            if section is None
        ]
