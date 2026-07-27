"""
Translate processed events and cluster snapshots into Prometheus metric updates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from typing import Any

from prometheus_client import Gauge

from videre.event_types import EventType, LifecycleEventType
from videre.events import (
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    Topic,
)
from videre.models import GpuHealthState, JobState, NodeHealthState

from ..cache.snapshot import ClusterHealthSnapshot
from .definitions import (
    BYTES_PER_MEGABYTE,
    CAPACITY_EVENTS,
    GPU_ERROR_EVENTS,
    GPU_HEALTH_STATE,
    GPU_MEMORY_TOTAL,
    GPU_MEMORY_USED,
    GPU_TEMPERATURE,
    GPU_UTILIZATION,
    JOB_COMPLETIONS,
    JOB_FAILURES,
    JOBS_BY_STATE,
    NODE_FAILURE_EVENTS,
    NODE_HEALTH_STATE,
    UNRESOLVED_FAILURES,
)

NODE_FAILURE_EVENT_TYPES: frozenset[str] = frozenset({
    EventType.NODE_KUBELET_DOWN.value,
    EventType.NODE_UNTOLERATED_TAINT.value,
    EventType.NODE_IMAGE_PULL_FAILURE.value,
    EventType.NODE_CNI_FAILURE.value,
    EventType.NODE_DISK_PRESSURE.value,
    EventType.NODE_DRAINED.value,
    EventType.NODE_HEALTH_CHECK_REMOVED.value,
})

GPU_ERROR_EVENT_TYPES: frozenset[str] = frozenset({
    EventType.GPU_THERMAL_THROTTLING.value,
    EventType.GPU_ECC_UNCORRECTABLE.value,
    EventType.GPU_XID_ERROR.value,
    EventType.GPU_NVLINK_DEGRADED.value,
    EventType.GPU_DRIVER_CRASH.value,
})

JOB_FAILURE_EVENT_TYPES: frozenset[str] = frozenset({
    EventType.JOB_OOM_KILL.value,
    EventType.JOB_NCCL_TIMEOUT.value,
    EventType.JOB_STRAGGLER.value,
    EventType.JOB_CHECKPOINT_CORRUPT.value,
    EventType.JOB_PREEMPTED.value,
})

CAPACITY_EVENT_TYPES: frozenset[str] = frozenset({
    EventType.CAPACITY_FRAGMENTATION.value,
    EventType.CAPACITY_RESERVED_IDLE.value,
})


def _set_health_state(
    gauge: Gauge,
    states: Iterable[StrEnum],
    active_state: str,
    **entity_labels: str
) -> None:
    for state in states:
        gauge.labels(**entity_labels, state=state.value).set(1.0 if state.value == active_state else 0.0)


def _record_node_event(message: NodeEventMessage) -> None:
    node = message.payload
    _set_health_state(NODE_HEALTH_STATE, NodeHealthState, node.health_state.value, node_id=node.id)
    
    if message.event_type in NODE_FAILURE_EVENT_TYPES:
        NODE_FAILURE_EVENTS.labels(node_id=node.id, failure_mode=message.event_type).inc()


def _record_gpu_event(message: GpuMetricMessage) -> None:
    gpu = message.payload
    entity_labels = {"node_id": gpu.node_id, "gpu_id": gpu.id}
    
    GPU_UTILIZATION.labels(**entity_labels).set(gpu.utilization_percentage)
    GPU_TEMPERATURE.labels(**entity_labels).set(gpu.temperature_celsius)
    GPU_MEMORY_USED.labels(**entity_labels).set(gpu.memory_used_mb * BYTES_PER_MEGABYTE)
    GPU_MEMORY_TOTAL.labels(**entity_labels).set(gpu.memory_total_mb * BYTES_PER_MEGABYTE)
    _set_health_state(GPU_HEALTH_STATE, GpuHealthState, gpu.health_state.value, **entity_labels)
    
    if message.event_type in GPU_ERROR_EVENT_TYPES:
        GPU_ERROR_EVENTS.labels(**entity_labels, error_type=message.event_type).inc()


def _record_job_event(message: JobEventMessage) -> None:
    if message.event_type == LifecycleEventType.JOB_COMPLETED.value:
        JOB_COMPLETIONS.inc()
    elif message.event_type in JOB_FAILURE_EVENT_TYPES:
        JOB_FAILURES.labels(failure_mode=message.event_type).inc()


def _record_scheduler_event(message: SchedulerEventMessage) -> None:
    if message.event_type in CAPACITY_EVENT_TYPES:
        CAPACITY_EVENTS.labels(event_type=message.event_type).inc()


_RECORDERS: dict[Topic, Callable[[Any], None]] = {
    Topic.NODE_EVENTS: _record_node_event,
    Topic.GPU_METRICS: _record_gpu_event,
    Topic.JOB_EVENTS: _record_job_event,
    Topic.SCHEDULER_EVENTS: _record_scheduler_event,
}


def record_event(topic: Topic, message: Any) -> None:
    _RECORDERS[topic](message)


def record_cluster_snapshots(snapshots: Sequence[ClusterHealthSnapshot]) -> None:
    for snapshot in snapshots:
        for job_state in JobState:
            JOBS_BY_STATE.labels(
                cluster_id=snapshot.cluster_id, state=job_state.value
            ).set(
                snapshot.jobs_by_lifecycle_state.get(job_state.value, 0)
            )
    
    if snapshots:
        UNRESOLVED_FAILURES.set(snapshots[0].unresolved_failure_count)
