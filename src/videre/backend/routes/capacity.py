"""
GPU availability and current/historical capacity indicators.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from videre.database.tables import Gpu, Job, Node, SchedulerEventRecord
from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEventType

from ..dependencies import SessionDependency
from .schemas import CapacityResponse

router = APIRouter(prefix="/capacity", tags=["capacity"])

IDLE_UTILIZATION_THRESHOLD = 5.0
QUEUEING_DELAY_WINDOW = timedelta(days=3)


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return int((await session.execute(statement)).scalar_one())


@router.get("", response_model=list[CapacityResponse])
async def get_capacity(session: SessionDependency) -> list[CapacityResponse]:
    now = datetime.now(UTC)
    cutoff = now - QUEUEING_DELAY_WINDOW
    cluster_ids = (await session.execute(select(Node.cluster_id).distinct())).scalars().all()
    summaries = []
    for cluster_id in cluster_ids:
        ready = Node.health_state == NodeHealthState.READY.value
        healthy = and_(ready, Gpu.health_state == GpuHealthState.HEALTHY.value)
        total_gpus, unavailable_gpus, degraded_gpus, idle_gpus, active_gpus = (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(or_(
                        Node.health_state != NodeHealthState.READY.value,
                        Gpu.health_state == GpuHealthState.FAILED.value,
                    )),
                    func.count().filter(and_(
                        ready,
                        Gpu.health_state.in_([
                            GpuHealthState.DEGRADED.value, GpuHealthState.THROTTLING.value,
                        ]),
                    )),
                    func.count().filter(and_(healthy, Gpu.utilization_percentage < IDLE_UTILIZATION_THRESHOLD)),
                    func.count().filter(and_(healthy, Gpu.utilization_percentage >= IDLE_UTILIZATION_THRESHOLD)),
                )
                .select_from(Gpu)
                .join(Node, Gpu.node_id == Node.id)
                .where(Node.cluster_id == cluster_id)
            )
        ).one()

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
        
        queueing_delay_events_count = await _count(
            session,
            select(func.count())
            .select_from(SchedulerEventRecord)
            .join(Node, SchedulerEventRecord.related_node_id == Node.id)
            .where(
                and_(
                    Node.cluster_id == cluster_id,
                    SchedulerEventRecord.type == SchedulerEventType.QUEUEING_DELAY.value,
                    SchedulerEventRecord.timestamp >= cutoff,
                    SchedulerEventRecord.timestamp <= now,
                )
            )
        )
        
        summaries.append(
            CapacityResponse(
                cluster_id=cluster_id,
                total_gpus=total_gpus,
                unavailable_gpus=unavailable_gpus,
                degraded_gpus=degraded_gpus,
                idle_gpus=idle_gpus,
                active_gpus=active_gpus,
                idle_reserved_gpus=idle_gpus,
                drained_node_count=drained_nodes_count,
                unschedulable_node_count=unschedulable_nodes_count,
                queued_job_count=queued_jobs_count,
                queueing_delay_event_count=queueing_delay_events_count,
                fragmentation_event_count=queueing_delay_events_count,
            )
        )
    return summaries
