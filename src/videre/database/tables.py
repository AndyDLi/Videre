"""
PostgreSQL schema for materialized cluster state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEventType

SCHEMA_NAME = "videre"

# deterministic naming conventions for indexes, constraints, and keys
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA_NAME, naming_convention=NAMING_CONVENTION)


class FailureEntityTable(StrEnum):
    NODE = "node"
    GPU = "gpu"
    JOB = "job"


class FailureCategory(StrEnum):
    NODE_NOT_READY = "node_not_ready"
    GPU = "gpu"
    JOB = "job"
    CAPACITY = "capacity"


def enum_check(column_name: str, enum_type: type[StrEnum]) -> CheckConstraint:
    allowed = ", ".join(f"'{member.value}'" for member in enum_type)
    return CheckConstraint(f"{column_name} IN ({allowed})", name=f"{column_name}_valid")


# Current-state tables

class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (
        CheckConstraint(
            "(simulation_run_id IS NULL) = (simulation_run_started_at IS NULL)", name="simulation_run_paired",
        ),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    simulation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    simulation_run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        enum_check("health_state", NodeHealthState),
        Index("ix_nodes_health_state", "health_state")
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gpus: Mapped[list[Gpu]] = relationship(cascade="all, delete-orphan")
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    health_state: Mapped[str] = mapped_column(String(32), nullable=False)
    simulated_node_label: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Gpu(Base):
    __tablename__ = "gpus"
    __table_args__ = (
        enum_check("health_state", GpuHealthState),
        Index("ix_gpus_health_state", "health_state")
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    utilization_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_celsius: Mapped[float] = mapped_column(Float, nullable=False)
    memory_used_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_total_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    ecc_correctable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ecc_uncorrectable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    xid_error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    health_state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("lifecycle_state", JobState),
        Index("ix_jobs_lifecycle_state", "lifecycle_state"),
        Index("ix_jobs_updated_at", "updated_at"),    # retention prunes by the last event a job received
    )
    
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_assignments: Mapped[list[JobNodeAssignment]] = relationship(cascade="all, delete-orphan")
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_memory_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pod_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    last_checkpoint_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint_corrupt: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobNodeAssignment(Base):
    """
    Join table recording which simulated node(s) each job is assigned to and vice versa (many-to-many relationship).
    """
    
    __tablename__ = "job_node_assignments"
    
    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True, index=True
    )


# Append-only tables

class SchedulerEventRecord(Base):
    __tablename__ = "scheduler_events"
    __table_args__ = (
        enum_check("type", SchedulerEventType),
        CheckConstraint(
            "(type = 'QUEUEING_DELAY') = (delay_seconds IS NOT NULL)", name="delay_matches_type"
        ),
        Index("ix_scheduler_events_timestamp", "timestamp"),
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    related_job_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_node_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class FailureRecord(Base):
    __tablename__ = "failure_records"
    __table_args__ = (
        enum_check("entity_type", FailureEntityTable),
        enum_check("category", FailureCategory),
        Index("ix_failure_records_detected_at", "detected_at"),
        Index("ix_failure_records_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_failure_records_correlation_id", "correlation_id"),
        Index(
            "ix_failure_records_unresolved",
            "entity_type",
            "entity_id",
            postgresql_where=text("resolved_at IS NULL")
        )
    )
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    root_cause_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("failure_records.id", ondelete="SET NULL"), nullable=True
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
