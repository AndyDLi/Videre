"""
Structured state and failure history for one entity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from videre.database.tables import (
    FailureEntityTable,
    FailureRecord,
    Gpu,
    Job,
    Node,
    SchedulerEventRecord,
)

from .context import (
    FailureRecordContext,
    GpuStateContext,
    JobStateContext,
    NodeStateContext,
    PostgresContext,
    SchedulerEventContext,
)

RESOLVED_HISTORY_WINDOW = timedelta(hours=1)
FAILURE_LIMIT = 20
SCHEDULER_EVENT_LIMIT = 20


def _failure_scope(pairs: list[tuple[FailureEntityTable, str]]) -> ColumnElement[bool]:
    return or_(
        *[
            and_(
                FailureRecord.entity_type == entity_type.value,
                FailureRecord.entity_id == entity_id
            )
            for entity_type, entity_id in pairs
        ]
    )


async def _load_failures(
    session: AsyncSession,
    pairs: list[tuple[FailureEntityTable, str]]
) -> tuple[list[FailureRecordContext], list[FailureRecordContext]]:
    if not pairs:
        return [], []
    
    scope = _failure_scope(pairs)
    resolved_cutoff = datetime.now(UTC) - RESOLVED_HISTORY_WINDOW
    
    unresolved = (
        await session.execute(
            select(FailureRecord)
            .where(scope, FailureRecord.resolved_at.is_(None))
            .order_by(FailureRecord.detected_at.desc())
            .limit(FAILURE_LIMIT)
        )
    ).scalars().all()
    recently_resolved = (
        await session.execute(
            select(FailureRecord)
            .where(scope, FailureRecord.resolved_at.is_not(None), FailureRecord.resolved_at >= resolved_cutoff)
            .order_by(FailureRecord.resolved_at.desc())
            .limit(FAILURE_LIMIT)
        )
    ).scalars().all()
    
    return (
        [FailureRecordContext.model_validate(row) for row in unresolved],
        [FailureRecordContext.model_validate(row) for row in recently_resolved]
    )


async def _load_scheduler_events(
    session: AsyncSession,
    *,
    node_id: str | None = None,
    job_id: str | None = None
) -> list[SchedulerEventContext]:
    filters = []
    if node_id is not None:
        filters.append(SchedulerEventRecord.related_node_id == node_id)
    if job_id is not None:
        filters.append(SchedulerEventRecord.related_job_id == job_id)
    if not filters:
        return []
    
    rows = (
        await session.execute(
            select(SchedulerEventRecord)
            .where(or_(*filters))
            .order_by(SchedulerEventRecord.timestamp.desc())
            .limit(SCHEDULER_EVENT_LIMIT)
        )
    ).scalars().all()
    
    return [SchedulerEventContext.model_validate(row) for row in rows]


async def _node_context(session: AsyncSession, node_id: str) -> PostgresContext | None:
    node = (
        await session.execute(
            select(Node)
            .where(Node.id == node_id)
            .options(
                selectinload(Node.gpus),
            )
        )
    ).scalar_one_or_none()
    if node is None:
        return None
    
    gpus = sorted(node.gpus, key=lambda gpu: gpu.id)
    scope: list[tuple[FailureEntityTable, str]] = [(FailureEntityTable.NODE, node.id)]
    scope.extend((FailureEntityTable.GPU, gpu.id) for gpu in gpus)
    unresolved, recently_resolved = await _load_failures(session, scope)
    
    return PostgresContext(
        node=NodeStateContext.model_validate(node),
        gpus=[GpuStateContext.model_validate(gpu) for gpu in gpus],
        unresolved_failures=unresolved,
        recently_resolved_failures=recently_resolved,
        scheduler_events=await _load_scheduler_events(session, node_id=node.id)
    )


async def _gpu_context(session: AsyncSession, gpu_id: str) -> PostgresContext | None:
    gpu = (
        await session.execute(
            select(Gpu)
            .where(Gpu.id == gpu_id)
        )
    ).scalar_one_or_none()
    if gpu is None:
        return None
    
    node = (
        await session.execute(
            select(Node)
            .where(Node.id == gpu.node_id)
        )
    ).scalar_one_or_none()
    scope = [(FailureEntityTable.GPU, gpu.id), (FailureEntityTable.NODE, gpu.node_id)]
    unresolved, recently_resolved = await _load_failures(session, scope)
    
    return PostgresContext(
        node=None if node is None else NodeStateContext.model_validate(node),
        gpus=[GpuStateContext.model_validate(gpu)],
        unresolved_failures=unresolved,
        recently_resolved_failures=recently_resolved,
        scheduler_events=await _load_scheduler_events(session, node_id=gpu.node_id)
    )


async def _job_context(session: AsyncSession, job_id: str) -> PostgresContext | None:
    job = (
        await session.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(
                selectinload(Job.node_assignments),
            )
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    
    assigned_node_ids = sorted(assignment.node_id for assignment in job.node_assignments)
    state = JobStateContext.model_validate(job)
    state.assigned_node_ids = assigned_node_ids
    
    scope: list[tuple[FailureEntityTable, str]] = [(FailureEntityTable.JOB, job.id)]
    scope.extend((FailureEntityTable.NODE, node_id) for node_id in assigned_node_ids)
    unresolved, recently_resolved = await _load_failures(session, scope)
    
    return PostgresContext(
        job=state,
        unresolved_failures=unresolved,
        recently_resolved_failures=recently_resolved,
        scheduler_events=await _load_scheduler_events(session, job_id=job.id)
    )


async def load_postgres_context(
    session: AsyncSession,
    entity_type: FailureEntityTable,
    entity_id: str
) -> PostgresContext | None:
    if entity_type == FailureEntityTable.NODE:
        return await _node_context(session, entity_id)
    if entity_type == FailureEntityTable.GPU:
        return await _gpu_context(session, entity_id)
    return await _job_context(session, entity_id)
