"""
Build cluster-health snapshots from Postgres.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import Cluster, FailureRecord, Gpu, Job, Node

from .snapshot import ClusterHealthSnapshot


async def _grouped_counts(session: AsyncSession, statement: Select[tuple[str, int]]) -> dict[str, int]:
    return {state: count for state, count in (await session.execute(statement)).all()}


async def build_snapshot(session: AsyncSession, cluster: Cluster) -> ClusterHealthSnapshot:
    nodes_by_health_state = await _grouped_counts(
        session,
        select(Node.health_state, func.count())
        .where(Node.cluster_id == cluster.id)
        .group_by(Node.health_state)
    )
    gpus_by_health_state = await _grouped_counts(
        session,
        select(Gpu.health_state, func.count())
        .join(Node, Gpu.node_id == Node.id)
        .where(Node.cluster_id == cluster.id)
        .group_by(Gpu.health_state)
    )
    jobs_by_lifecycle_state = await _grouped_counts(
        session,
        select(Job.lifecycle_state, func.count())
        .where(Job.cluster_id == cluster.id)
        .group_by(Job.lifecycle_state)
    )
    unresolved = await session.execute(
        select(func.count())
        .select_from(FailureRecord)
        .where(FailureRecord.resolved_at.is_(None))
    )
    
    return ClusterHealthSnapshot(
        cluster_id=cluster.id,
        cluster_name=cluster.name,
        nodes_by_health_state=nodes_by_health_state,
        gpus_by_health_state=gpus_by_health_state,
        jobs_by_lifecycle_state=jobs_by_lifecycle_state,
        unresolved_failure_count=int(unresolved.scalar_one())
    )


async def build_all_snapshots(session: AsyncSession) -> list[ClusterHealthSnapshot]:
    statement = select(Cluster).where(select(Node.id).where(Node.cluster_id == Cluster.id).exists())
    clusters = (await session.execute(statement)).scalars().all()
    return [await build_snapshot(session, cluster) for cluster in clusters]
