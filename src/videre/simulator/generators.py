"""
Map a fired ScheduledEvent to an entity mutation and a publishable Kafka event message.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random
from uuid import uuid4

from pydantic import BaseModel

from videre.events import (
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    Topic,
)
from videre.models import (
    GPU,
    GpuHealthState,
    Job,
    JobState,
    Node,
    NodeHealthState,
    SchedulerEvent,
    SchedulerEventType,
)

from .cluster_state import ClusterState
from .correlation import ScheduledEvent
from .event_types import EventType


@dataclass(frozen=True)
class GeneratedEvent:
    topic: Topic
    key: str
    message: BaseModel


Generator = Callable[[ClusterState, ScheduledEvent, Random], "GeneratedEvent | None"]


# --- Message builders ---

def make_node_message(event_type: str, correlation_id: str, node: Node) -> GeneratedEvent:
    message = NodeEventMessage(event_type=event_type, correlation_id=correlation_id, payload=node)
    return GeneratedEvent(topic=Topic.NODE_EVENTS, key=node.id, message=message)


def make_gpu_message(event_type: str, correlation_id: str, gpu: GPU) -> GeneratedEvent:
    message = GpuMetricMessage(event_type=event_type, correlation_id=correlation_id, payload=gpu)
    return GeneratedEvent(topic=Topic.GPU_METRICS, key=gpu.node_id, message=message)


def make_job_message(event_type: str, correlation_id: str, job: Job) -> GeneratedEvent:
    message = JobEventMessage(event_type=event_type, correlation_id=correlation_id, payload=job)
    return GeneratedEvent(topic=Topic.JOB_EVENTS, key=job.id, message=message)


def make_scheduler_message(
    event_type: str, correlation_id: str, scheduler_event: SchedulerEvent
) -> GeneratedEvent:
    message = SchedulerEventMessage(
        event_type=event_type, correlation_id=correlation_id, payload=scheduler_event
    )
    key = scheduler_event.job_id or scheduler_event.node_id or scheduler_event.id
    return GeneratedEvent(topic=Topic.SCHEDULER_EVENTS, key=key, message=message)


# --- Entity selection ---

def _pick_gpu(state: ClusterState, event: ScheduledEvent, random_generator: Random) -> GPU | None:
    if event.target.gpu_id is not None:
        return state.gpus.get(event.target.gpu_id)
    candidates = state.gpus_on_node(event.target.node_id)
    return random_generator.choice(candidates) if candidates else None


def _pick_running_job(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> Job | None:
    if event.target.job_id is not None:
        return state.jobs.get(event.target.job_id)
    candidates = state.running_jobs_on_node(event.target.node_id)
    return random_generator.choice(candidates) if candidates else None


# --- Node-level generators ---

def generate_node_not_ready(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    node = state.nodes.get(event.target.node_id)
    if node is None:
        return None
    node.health_state = NodeHealthState.NOT_READY
    return make_node_message(event.event_type.value, event.correlation_id, node)


# --- GPU-level generators ---

def generate_gpu_thermal_throttling(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    gpu = _pick_gpu(state, event, random_generator)
    if gpu is None:
        return None
    gpu.health_state = GpuHealthState.THROTTLING
    gpu.temperature_celsius = 92.0
    return make_gpu_message(event.event_type.value, event.correlation_id, gpu)


def generate_gpu_ecc_uncorrectable(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    gpu = _pick_gpu(state, event, random_generator)
    if gpu is None:
        return None
    gpu.ecc_uncorrectable_count += 1
    gpu.health_state = GpuHealthState.DEGRADED
    return make_gpu_message(event.event_type.value, event.correlation_id, gpu)


def generate_gpu_xid_error(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    gpu = _pick_gpu(state, event, random_generator)
    if gpu is None:
        return None
    gpu.xid_error_count += 1
    gpu.health_state = GpuHealthState.DEGRADED
    return make_gpu_message(event.event_type.value, event.correlation_id, gpu)


def generate_gpu_nvlink_degraded(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    gpu = _pick_gpu(state, event, random_generator)
    if gpu is None:
        return None
    gpu.health_state = GpuHealthState.DEGRADED
    return make_gpu_message(event.event_type.value, event.correlation_id, gpu)


def generate_gpu_driver_crash(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    gpu = _pick_gpu(state, event, random_generator)
    if gpu is None:
        return None
    gpu.health_state = GpuHealthState.FAILED
    return make_gpu_message(event.event_type.value, event.correlation_id, gpu)


# --- Job-level generators ---

_JOB_FAILURE_REASONS: dict[EventType, str] = {
    EventType.JOB_OOM_KILL: "OOMKilled",
    EventType.JOB_NCCL_TIMEOUT: "NCCL collective timeout",
    EventType.JOB_PREEMPTED: "preempted by higher-priority job",
}


def generate_job_failure(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    job = _pick_running_job(state, event, random_generator)
    if job is None:
        return None
    job.state = JobState.FAILED
    job.failure_reason = _JOB_FAILURE_REASONS[event.event_type]
    return make_job_message(event.event_type.value, event.correlation_id, job)


def generate_job_straggler(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    job = _pick_running_job(state, event, random_generator)
    if job is None:
        return None
    return make_job_message(event.event_type.value, event.correlation_id, job)


def generate_job_checkpoint_corrupt(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    job = _pick_running_job(state, event, random_generator)
    if job is None:
        return None
    job.checkpoint_corrupt = True
    return make_job_message(event.event_type.value, event.correlation_id, job)


# --- Capacity-level generators ---

def generate_capacity_fragmentation(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    scheduler_event = SchedulerEvent(
        id=str(uuid4()),
        type=SchedulerEventType.QUEUEING_DELAY,
        node_id=event.target.node_id,
        delay_seconds=random_generator.uniform(30.0, 300.0),
        reason="resource fragmentation delayed placement",
    )
    return make_scheduler_message(event.event_type.value, event.correlation_id, scheduler_event)


def generate_node_drained(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    node = state.nodes.get(event.target.node_id)
    if node is None:
        return None
    node.health_state = NodeHealthState.DRAINING
    return make_node_message(event.event_type.value, event.correlation_id, node)


def generate_capacity_reserved_idle(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    scheduler_event = SchedulerEvent(
        id=str(uuid4()),
        type=SchedulerEventType.PLACEMENT,
        node_id=event.target.node_id,
        reason="reserved-but-idle GPUs reducing usable capacity",
    )
    return make_scheduler_message(event.event_type.value, event.correlation_id, scheduler_event)


def generate_node_health_check_removed(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    node = state.nodes.get(event.target.node_id)
    if node is None:
        return None
    node.health_state = NodeHealthState.CORDONED
    return make_node_message(event.event_type.value, event.correlation_id, node)


# --- Registry ---

GENERATORS: dict[EventType, Generator] = {
    # Node-level
    EventType.NODE_KUBELET_DOWN: generate_node_not_ready,
    EventType.NODE_UNTOLERATED_TAINT: generate_node_not_ready,
    EventType.NODE_IMAGE_PULL_FAILURE: generate_node_not_ready,
    EventType.NODE_CNI_FAILURE: generate_node_not_ready,
    EventType.NODE_DISK_PRESSURE: generate_node_not_ready,
    
    # GPU-level
    EventType.GPU_THERMAL_THROTTLING: generate_gpu_thermal_throttling,
    EventType.GPU_ECC_UNCORRECTABLE: generate_gpu_ecc_uncorrectable,
    EventType.GPU_XID_ERROR: generate_gpu_xid_error,
    EventType.GPU_NVLINK_DEGRADED: generate_gpu_nvlink_degraded,
    EventType.GPU_DRIVER_CRASH: generate_gpu_driver_crash,
    
    # Job-level
    EventType.JOB_OOM_KILL: generate_job_failure,
    EventType.JOB_NCCL_TIMEOUT: generate_job_failure,
    EventType.JOB_STRAGGLER: generate_job_straggler,
    EventType.JOB_CHECKPOINT_CORRUPT: generate_job_checkpoint_corrupt,
    EventType.JOB_PREEMPTED: generate_job_failure,
    
    # Capacity-level
    EventType.CAPACITY_FRAGMENTATION: generate_capacity_fragmentation,
    EventType.NODE_DRAINED: generate_node_drained,
    EventType.CAPACITY_RESERVED_IDLE: generate_capacity_reserved_idle,
    EventType.NODE_HEALTH_CHECK_REMOVED: generate_node_health_check_removed,
}


def generate(
    state: ClusterState, event: ScheduledEvent, random_generator: Random
) -> GeneratedEvent | None:
    generator = GENERATORS.get(event.event_type)
    if generator is None:
        return None
    return generator(state, event, random_generator)
