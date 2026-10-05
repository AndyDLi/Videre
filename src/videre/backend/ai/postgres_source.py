"""
Structured state and failure history for one entity.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from videre.database.tables import (
    FailureEntityTable,
    FailureRecord,
    Gpu,
    Job,
    JobNodeAssignment,
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
ASSIGNED_NODE_LIMIT = 8
GPU_LIMIT = 64


def _bounded[T](rows: Sequence[T], limit: int, section: str, context: PostgresContext) -> list[T]:
    if len(rows) > limit:
        context.truncated_sections.append(section)
    return list(rows[:limit])


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
    pairs: list[tuple[FailureEntityTable, str]],
    cluster_id: str,
    context: PostgresContext,
) -> None:
    scope = _failure_scope(pairs)
    resolved_cutoff = datetime.now(UTC) - RESOLVED_HISTORY_WINDOW
    unresolved = (
        await session.execute(
            select(FailureRecord)
            .where(scope, FailureRecord.resolved_at.is_(None))
            .order_by(FailureRecord.detected_at.desc(), FailureRecord.id)
            .limit(FAILURE_LIMIT + 1)
        )
    ).scalars().all()
    recently_resolved = (
        await session.execute(
            select(FailureRecord)
            .where(scope, FailureRecord.resolved_at >= resolved_cutoff)
            .order_by(FailureRecord.resolved_at.desc(), FailureRecord.id)
            .limit(FAILURE_LIMIT + 1)
        )
    ).scalars().all()
    context.unresolved_failures = [FailureRecordContext.model_validate(row) for row in
        _bounded(unresolved, FAILURE_LIMIT, "unresolved_failures", context)]
    context.recently_resolved_failures = [FailureRecordContext.model_validate(row) for row in
        _bounded(recently_resolved, FAILURE_LIMIT, "recently_resolved_failures", context)]
    direct = context.unresolved_failures + context.recently_resolved_failures
    correlation_ids = sorted({row.correlation_id for row in direct if row.correlation_id.strip()})
    if not correlation_ids:
        return

    # only include correlated failures from the requested cluster.
    cluster_scope = or_(
        and_(FailureRecord.entity_type == "node", FailureRecord.entity_id.in_(
            select(Node.id).where(Node.cluster_id == cluster_id))),
        and_(FailureRecord.entity_type == "gpu", FailureRecord.entity_id.in_(
            select(Gpu.id).join(Node, Node.id == Gpu.node_id).where(Node.cluster_id == cluster_id))),
        and_(FailureRecord.entity_type == "job", FailureRecord.entity_id.in_(
            select(Job.id).where(Job.cluster_id == cluster_id))),
    )
    related = (
        await session.execute(
            select(FailureRecord).where(
                cluster_scope,
                FailureRecord.correlation_id.in_(correlation_ids),
                FailureRecord.id.not_in([row.id for row in direct]),
                or_(FailureRecord.resolved_at.is_(None), FailureRecord.resolved_at >= resolved_cutoff),
            ).order_by(
                FailureRecord.resolved_at.is_(None).desc(),
                func.coalesce(FailureRecord.resolved_at, FailureRecord.detected_at).desc(),
                FailureRecord.id,
            ).limit(FAILURE_LIMIT + 1)
        )
    ).scalars().all()
    context.correlated_failures = [FailureRecordContext.model_validate(row) for row in
        _bounded(related, FAILURE_LIMIT, "correlated_failures", context)]


async def _load_scheduler_events(
    session: AsyncSession,
    context: PostgresContext,
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
            .order_by(SchedulerEventRecord.timestamp.desc(), SchedulerEventRecord.id)
            .limit(SCHEDULER_EVENT_LIMIT + 1)
        )
    ).scalars().all()
    return [SchedulerEventContext.model_validate(row) for row in
        _bounded(rows, SCHEDULER_EVENT_LIMIT, "scheduler_events", context)]


async def _load_gpus(session: AsyncSession, node_ids: list[str], context: PostgresContext) -> None:
    if not node_ids:
        return
    rows = (await session.execute(
        select(Gpu).where(Gpu.node_id.in_(node_ids)).order_by(Gpu.id).limit(GPU_LIMIT + 1)
    )).scalars().all()
    context.gpus = [GpuStateContext.model_validate(row) for row in
        _bounded(rows, GPU_LIMIT, "gpus", context)]


async def _node_context(session: AsyncSession, node_id: str) -> PostgresContext | None:
    node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
    if node is None:
        return None
    context = PostgresContext(node=NodeStateContext.model_validate(node))
    await _load_gpus(session, [node.id], context)
    context.scheduler_events = await _load_scheduler_events(session, context, node_id=node.id)
    return context


async def _gpu_context(session: AsyncSession, gpu_id: str) -> PostgresContext | None:
    gpu = (await session.execute(select(Gpu).where(Gpu.id == gpu_id))).scalar_one_or_none()
    if gpu is None:
        return None
    node = (await session.execute(select(Node).where(Node.id == gpu.node_id))).scalar_one_or_none()
    context = PostgresContext(
        node=None if node is None else NodeStateContext.model_validate(node),
        gpus=[GpuStateContext.model_validate(gpu)],
    )
    context.scheduler_events = await _load_scheduler_events(session, context, node_id=gpu.node_id)
    return context


async def _job_context(session: AsyncSession, job_id: str) -> PostgresContext | None:
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        return None
    context = PostgresContext(job=JobStateContext.model_validate(job))
    nodes = (await session.execute(
        select(Node).join(JobNodeAssignment, JobNodeAssignment.node_id == Node.id)
        .where(JobNodeAssignment.job_id == job.id, Node.cluster_id == job.cluster_id)
        .order_by(Node.id).limit(ASSIGNED_NODE_LIMIT + 1)
    )).scalars().all()
    context.assigned_nodes = [NodeStateContext.model_validate(row) for row in
        _bounded(nodes, ASSIGNED_NODE_LIMIT, "assigned_nodes", context)]
    assigned_ids = [node.id for node in context.assigned_nodes]
    assert context.job is not None
    context.job.assigned_node_ids = assigned_ids
    await _load_gpus(session, assigned_ids, context)
    context.scheduler_events = await _load_scheduler_events(session, context, job_id=job.id)
    return context


async def load_postgres_context(
    session: AsyncSession,
    entity_type: FailureEntityTable,
    entity_id: str
) -> PostgresContext | None:
    if entity_type == FailureEntityTable.NODE:
        context = await _node_context(session, entity_id)
    elif entity_type == FailureEntityTable.GPU:
        context = await _gpu_context(session, entity_id)
    else:
        context = await _job_context(session, entity_id)
    if context is None:
        return None
    pairs: list[tuple[FailureEntityTable, str]] = []
    if context.job is not None:
        cluster_id = context.job.cluster_id
        pairs.append((FailureEntityTable.JOB, context.job.id))
    else:
        assert context.node is not None
        cluster_id = context.node.cluster_id
    for node in ([context.node] if context.node is not None else context.assigned_nodes):
        pairs.append((FailureEntityTable.NODE, node.id))
    pairs.extend((FailureEntityTable.GPU, gpu.id) for gpu in context.gpus)
    await _load_failures(session, pairs, cluster_id, context)
    return context
