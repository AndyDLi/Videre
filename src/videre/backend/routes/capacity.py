"""
Capacity-bottleneck analysis: where usable capacity it being lost.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import Gpu, Job, JobNodeAssignment, Node, SchedulerEventRecord
from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEventType

from ..dependencies import SessionDependency
from .schemas import CapacityResponse

router = APIRouter(prefix="/capacity", tags=["capacity"])

IDLE_UTILIZATION_THRESHOLD = 5.0
FRAGMENTATION_WINDOW = timedelta(days=3)


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return int((await session.execute(statement)).scalar_one())


@router.get("", response_model=list[CapacityResponse])
async def get_capacity(session: SessionDependency) -> list[CapacityResponse]:
    cluster_ids = (await session.execute(select(Node.cluster_id).distinct())).scalars().all()
    summaries = []
    for cluster_id in cluster_ids:
        total_gpus = await _count(
            session,
            select(func.count())
            .select_from(Gpu)
            .join(Node, Gpu.node_id == Node.id)
            .where(Node.cluster_id == cluster_id)
        )
        
        unavailable_gpus = await _count(
            session,
            select(func.count())
            .select_from(Gpu)
            .join(Node, Gpu.node_id == Node.id)
            .where(
                Node.cluster_id == cluster_id, Node.health_state != NodeHealthState.READY.value
            )
        )
        
        busy_node_ids = (
            select(JobNodeAssignment.node_id)
            .join(Job, Job.id == JobNodeAssignment.job_id)
            .where(Job.lifecycle_state == JobState.RUNNING.value)
            .scalar_subquery()
        )
        
        idle_reserved_gpus = await _count(
            session,
            select(func.count())
            .select_from(Gpu)
            .join(Node, Gpu.node_id == Node.id)
            .where(
                Node.cluster_id == cluster_id,
                Node.health_state == NodeHealthState.READY.value,
                Gpu.health_state == GpuHealthState.HEALTHY.value,
                Gpu.utilization_percentage < IDLE_UTILIZATION_THRESHOLD,
                Node.id.not_in(busy_node_ids),
            ),
        )
        
        drained_nodes_count = await _count(
            session,
            select(func.count())
            .select_from(Node)
            .where(
                Node.cluster_id == cluster_id,
                Node.health_state == NodeHealthState.DRAINING.value,
            ),
        )
        
        unschedulable_nodes_count = await _count(
            session,
            select(func.count())
            .select_from(Node)
            .where(
                Node.cluster_id == cluster_id,
                Node.health_state == NodeHealthState.CORDONED.value,
            ),
        )
        
        queued_jobs_count = await _count(
            session,
            select(func.count())
            .select_from(Job)
            .where(
                Job.cluster_id == cluster_id,
                Job.lifecycle_state == JobState.PENDING.value,
            ),
        )
        
        cutoff = datetime.now(UTC) - FRAGMENTATION_WINDOW
        fragmentation_events_count = await _count(
            session,
            select(func.count())
            .select_from(SchedulerEventRecord)
            .join(Node, SchedulerEventRecord.related_node_id == Node.id)
            .where(
                and_(
                    Node.cluster_id == cluster_id,
                    SchedulerEventRecord.type == SchedulerEventType.QUEUEING_DELAY.value,
                    SchedulerEventRecord.timestamp >= cutoff,
                )
            )
        )
        
        summaries.append(
            CapacityResponse(
                cluster_id=cluster_id,
                total_gpus=total_gpus,
                unavailable_gpus=unavailable_gpus,
                idle_reserved_gpus=idle_reserved_gpus,
                drained_node_count=drained_nodes_count,
                unschedulable_node_count=unschedulable_nodes_count,
                queued_job_count=queued_jobs_count,
                fragmentation_event_count=fragmentation_events_count,
            )
        )
    return summaries
