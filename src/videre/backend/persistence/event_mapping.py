"""
Map one Kafka event message onto its Postgres rows.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import (
    Cluster,
    FailureCategory,
    FailureEntityTable,
    FailureRecord,
    Gpu,
    Job,
    JobNodeAssignment,
    Node,
    SchedulerEventRecord,
)
from videre.event_types import EventType, LifecycleEventType
from videre.events import (
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    SimulationRun,
    Topic,
)
from videre.models import GpuHealthState, JobState, NodeHealthState

PLACEHOLDER_CLUSTER_ID = "unknown"

FAILURE_CATEGORIES: dict[EventType, FailureCategory] = {
    EventType.NODE_KUBELET_DOWN: FailureCategory.NODE_NOT_READY,
    EventType.NODE_UNTOLERATED_TAINT: FailureCategory.NODE_NOT_READY,
    EventType.NODE_IMAGE_PULL_FAILURE: FailureCategory.NODE_NOT_READY,
    EventType.NODE_CNI_FAILURE: FailureCategory.NODE_NOT_READY,
    EventType.NODE_DISK_PRESSURE: FailureCategory.NODE_NOT_READY,

    EventType.GPU_THERMAL_THROTTLING: FailureCategory.GPU,
    EventType.GPU_ECC_UNCORRECTABLE: FailureCategory.GPU,
    EventType.GPU_XID_ERROR: FailureCategory.GPU,
    EventType.GPU_NVLINK_DEGRADED: FailureCategory.GPU,
    EventType.GPU_DRIVER_CRASH: FailureCategory.GPU,

    EventType.JOB_OOM_KILL: FailureCategory.JOB,
    EventType.JOB_NCCL_TIMEOUT: FailureCategory.JOB,
    EventType.JOB_STRAGGLER: FailureCategory.JOB,
    EventType.JOB_CHECKPOINT_CORRUPT: FailureCategory.JOB,
    EventType.JOB_PREEMPTED: FailureCategory.JOB,

    EventType.CAPACITY_FRAGMENTATION: FailureCategory.CAPACITY,
    EventType.NODE_DRAINED: FailureCategory.CAPACITY,
    EventType.CAPACITY_RESERVED_IDLE: FailureCategory.CAPACITY,
    EventType.NODE_HEALTH_CHECK_REMOVED: FailureCategory.CAPACITY,
}

RESOLVING_EVENT_TYPES: frozenset[str] = frozenset(
    {LifecycleEventType.NODE_RECOVERED.value, LifecycleEventType.GPU_RECOVERED.value}
)

_FAILURE_EVENT_TYPES: frozenset[str] = frozenset(member.value for member in EventType)

_FINISHED_JOB_STATES = (JobState.COMPLETED, JobState.FAILED)


async def _ensure_cluster(session: AsyncSession, cluster_id: str) -> None:
    statement = insert(Cluster).values(id=cluster_id, name=cluster_id)
    await session.execute(statement.on_conflict_do_nothing(index_elements=[Cluster.id]))


async def _ensure_node(session: AsyncSession, node_id: str, cluster_id: str) -> None:
    await _ensure_cluster(session, cluster_id)
    statement = insert(Node).values(
        id=node_id,
        cluster_id=cluster_id,
        cpu_cores=0,
        memory_gb=0,
        gpu_count=0,
        health_state=NodeHealthState.READY.value,
        simulated_node_label=node_id,
    )
    await session.execute(statement.on_conflict_do_nothing(index_elements=[Node.id]))


async def _ensure_job(session: AsyncSession, job_id: str, cluster_id: str) -> None:
    await _ensure_cluster(session, cluster_id)
    statement = insert(Job).values(
        id=job_id,
        cluster_id=cluster_id,
        lifecycle_state=JobState.PENDING.value,
        requested_cpu_cores=0,
        requested_memory_gb=0,
        requested_gpu_count=0,
    )
    await session.execute(statement.on_conflict_do_nothing(index_elements=[Job.id]))


async def _record_or_resolve_failure(
    session: AsyncSession,
    message: Any,
    entity_type: FailureEntityTable,
    entity_id: str,
) -> None:
    if message.event_type in RESOLVING_EVENT_TYPES:
        await session.execute(
            update(FailureRecord)
            .where(
                FailureRecord.entity_type == entity_type.value,
                FailureRecord.entity_id == entity_id,
                FailureRecord.resolved_at.is_(None),
            )
            .values(resolved_at=message.timestamp)
        )
        return
    
    if message.event_type not in _FAILURE_EVENT_TYPES:
        return
    
    statement = insert(FailureRecord).values(
        id=str(uuid4()),
        event_id=message.event_id,
        entity_type=entity_type.value,
        entity_id=entity_id,
        category=FAILURE_CATEGORIES[EventType(message.event_type)].value,
        root_cause_tag=message.event_type,
        correlation_id=message.correlation_id,
        detected_at=message.timestamp,
    )
    await session.execute(statement.on_conflict_do_nothing(index_elements=["event_id"]))


async def _apply_node_event(session: AsyncSession, message: NodeEventMessage) -> None:
    node = message.payload
    await _ensure_cluster(session, node.cluster_id)
    
    values = {
        "id": node.id,
        "cluster_id": node.cluster_id,
        "cpu_cores": node.cpu_cores,
        "memory_gb": node.memory_gb,
        "gpu_count": node.gpu_count,
        "health_state": node.health_state.value,
        "simulated_node_label": node.id,
        "updated_at": message.timestamp,
    }
    statement = insert(Node).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Node.id],
            set_={key: statement.excluded[key] for key in values if key != "id"},
        )
    )
    await _record_or_resolve_failure(session, message, FailureEntityTable.NODE, node.id)


async def _apply_gpu_event(session: AsyncSession, message: GpuMetricMessage) -> None:
    gpu = message.payload
    cluster_id = message.simulation_run.cluster_id if message.simulation_run is not None else PLACEHOLDER_CLUSTER_ID
    await _ensure_node(session, gpu.node_id, cluster_id)
    
    values = {
        "id": gpu.id,
        "node_id": gpu.node_id,
        "utilization_percentage": gpu.utilization_percentage,
        "temperature_celsius": gpu.temperature_celsius,
        "memory_used_mb": gpu.memory_used_mb,
        "memory_total_mb": gpu.memory_total_mb,
        "ecc_correctable_count": gpu.ecc_correctable_count,
        "ecc_uncorrectable_count": gpu.ecc_uncorrectable_count,
        "xid_error_count": gpu.xid_error_count,
        "health_state": gpu.health_state.value,
        "last_updated_at": message.timestamp,
    }
    statement = insert(Gpu).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Gpu.id],
            set_={key: statement.excluded[key] for key in values if key != "id"}
        )
    )
    await _record_or_resolve_failure(session, message, FailureEntityTable.GPU, gpu.id)


async def _apply_job_event(session: AsyncSession, message: JobEventMessage) -> None:
    job = message.payload
    await _ensure_cluster(session, job.cluster_id)
    
    completed_at = job.finished_at
    if completed_at is None and job.state in _FINISHED_JOB_STATES:
        completed_at = message.timestamp
    
    values = {
        "id": job.id,
        "cluster_id": job.cluster_id,
        "lifecycle_state": job.state.value,
        "requested_cpu_cores": job.resources.cpu_cores,
        "requested_memory_gb": job.resources.memory_gb,
        "requested_gpu_count": job.resources.gpu_count,
        "priority": job.priority,
        "pod_name": job.pod_name,
        "last_checkpoint_time": job.last_checkpoint_time,
        "checkpoint_corrupt": job.checkpoint_corrupt,
        "failure_reason": job.failure_reason,
        "created_at": job.created_at,
        "updated_at": message.timestamp,
        "started_at": job.started_at,
        "completed_at": completed_at,
    }
    statement = insert(Job).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Job.id],
            set_={key: statement.excluded[key] for key in values if key not in ("id", "created_at")},
        )
    )
    
    for node_id in job.assigned_node_ids:
        await _ensure_node(session, node_id, job.cluster_id)
        assignment = insert(JobNodeAssignment).values(job_id=job.id, node_id=node_id)
        await session.execute(
            assignment.on_conflict_do_nothing(index_elements=[JobNodeAssignment.job_id, JobNodeAssignment.node_id])
        )
    
    await _record_or_resolve_failure(session, message, FailureEntityTable.JOB, job.id)


async def _apply_scheduler_event(session: AsyncSession, message: SchedulerEventMessage) -> None:
    scheduler_event = message.payload
    cluster_id = message.simulation_run.cluster_id if message.simulation_run is not None else PLACEHOLDER_CLUSTER_ID
    if scheduler_event.node_id is not None:
        await _ensure_node(session, scheduler_event.node_id, cluster_id)
    if scheduler_event.job_id is not None:
        await _ensure_job(session, scheduler_event.job_id, cluster_id)
    
    statement = insert(SchedulerEventRecord).values(
        id=scheduler_event.id,
        event_id=message.event_id,
        type=scheduler_event.type.value,
        timestamp=scheduler_event.timestamp,
        related_job_id=scheduler_event.job_id,
        related_node_id=scheduler_event.node_id,
        delay_seconds=scheduler_event.delay_seconds,
        reason=scheduler_event.reason,
    )
    await session.execute(statement.on_conflict_do_nothing())

    if scheduler_event.node_id is not None:
        await _record_or_resolve_failure(session, message, FailureEntityTable.NODE, scheduler_event.node_id)


_HANDLERS: dict[Topic, Callable[[AsyncSession, Any], Awaitable[None]]] = {
    Topic.NODE_EVENTS: _apply_node_event,
    Topic.GPU_METRICS: _apply_gpu_event,
    Topic.JOB_EVENTS: _apply_job_event,
    Topic.SCHEDULER_EVENTS: _apply_scheduler_event,
}


class EventDisposition(StrEnum):
    APPLIED = "applied"
    STALE_RUN = "stale_run"
    LEGACY_AFTER_BOUNDARY = "legacy_after_boundary"
    CONFLICTING_RUN = "conflicting_run"


async def reconcile_run(session: AsyncSession, run: SimulationRun) -> EventDisposition:
    """Fence all topics and reconcile once, in the event's persistence transaction."""
    await _ensure_cluster(session, run.cluster_id)
    cluster = (await session.scalars(
        select(Cluster).where(Cluster.id == run.cluster_id).with_for_update()
        .execution_options(populate_existing=True)
    )).one()
    if cluster.simulation_run_id is not None:
        if cluster.simulation_run_id == str(run.run_id):
            return (
                EventDisposition.APPLIED if cluster.simulation_run_started_at == run.started_at
                else EventDisposition.CONFLICTING_RUN
            )
        if cluster.simulation_run_started_at == run.started_at:
            return EventDisposition.CONFLICTING_RUN
        if cluster.simulation_run_started_at is not None and run.started_at < cluster.simulation_run_started_at:
            return EventDisposition.STALE_RUN
    else:
        for table in (Node, Job):
            await session.execute(
                update(table).where(table.cluster_id == PLACEHOLDER_CLUSTER_ID)
                .values(cluster_id=run.cluster_id).execution_options(synchronize_session=False)
            )

    node_ids = select(Node.id).where(Node.cluster_id == run.cluster_id)
    gpu_ids = select(Gpu.id).where(Gpu.node_id.in_(node_ids))
    job_ids = select(Job.id).where(Job.cluster_id == run.cluster_id)
    await session.execute(
        update(FailureRecord).where(
            FailureRecord.resolved_at.is_(None),
            or_(
                and_(FailureRecord.entity_type == FailureEntityTable.NODE.value, FailureRecord.entity_id.in_(node_ids)),
                and_(FailureRecord.entity_type == FailureEntityTable.GPU.value, FailureRecord.entity_id.in_(gpu_ids)),
                and_(FailureRecord.entity_type == FailureEntityTable.JOB.value, FailureRecord.entity_id.in_(job_ids)),
            ),
        ).values(resolved_at=run.started_at).execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Job).where(Job.cluster_id == run.cluster_id, Job.lifecycle_state.in_(
            [JobState.PENDING.value, JobState.RUNNING.value],
        )).values(
            lifecycle_state=JobState.FAILED.value, failure_reason="simulation reset",
            completed_at=run.started_at, updated_at=run.started_at,
        ).execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Node).where(Node.cluster_id == run.cluster_id)
        .values(health_state=NodeHealthState.READY.value, updated_at=run.started_at)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Gpu).where(Gpu.node_id.in_(node_ids))
        .values(health_state=GpuHealthState.HEALTHY.value, last_updated_at=run.started_at)
        .execution_options(synchronize_session=False)
    )
    cluster.simulation_run_id = str(run.run_id)
    cluster.simulation_run_started_at = run.started_at
    await session.flush()
    return EventDisposition.APPLIED


async def apply_event(session: AsyncSession, topic: Topic, message: Any) -> EventDisposition:
    if message.simulation_run is None:
        has_boundary = await session.scalar(
            select(Cluster.id).where(Cluster.simulation_run_id.is_not(None)).limit(1)
        )
        if has_boundary is not None:
            return EventDisposition.LEGACY_AFTER_BOUNDARY
    else:
        disposition = await reconcile_run(session, message.simulation_run)
        if disposition is not EventDisposition.APPLIED:
            return disposition
    await _HANDLERS[topic](session, message)
    return EventDisposition.APPLIED
