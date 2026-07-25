from random import Random

import pytest

from videre.event_types import EventType
from videre.events import Topic
from videre.models import (
    GpuHealthState,
    Job,
    JobState,
    NodeHealthState,
    ResourceRequest,
    SchedulerEventType,
)
from videre.simulator.cluster_state import ClusterState, build_cluster_state
from videre.simulator.correlation import (
    BASELINE_FAILURE_WEIGHTS,
    CORRELATION_RULES,
    EventTarget,
    ScheduledEvent,
)
from videre.simulator.generators import GENERATORS, generate
from videre.simulator.job_lifecycle import JobLifecycle


def fired_event(event_type: EventType, node_id: str = "node-0") -> ScheduledEvent:
    return ScheduledEvent(event_type, EventTarget(node_id=node_id), 0.0, "correlation-1", 0)


def state_with_running_job(node_id: str = "node-0") -> ClusterState:
    state = build_cluster_state()
    state.jobs["job-1"] = Job(
        id="job-1",
        cluster_id="cluster-a",
        assigned_node_ids=[node_id],
        state=JobState.RUNNING,
        resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1),
    )
    return state


# --- Event-level ---


def test_every_event_type_has_a_generator() -> None:
    assert set(GENERATORS) == set(EventType)


def test_every_event_type_has_a_positive_baseline_weight() -> None:
    assert set(BASELINE_FAILURE_WEIGHTS) == set(EventType)
    assert all(weight > 0.0 for weight in BASELINE_FAILURE_WEIGHTS.values())


def test_every_correlation_rule_references_a_generator() -> None:
    referenced = {event_type for rule in CORRELATION_RULES for event_type in (rule.trigger, rule.downstream)}
    assert referenced <= set(GENERATORS)


# --- Node-level ---


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.NODE_KUBELET_DOWN,
        EventType.NODE_UNTOLERATED_TAINT,
        EventType.NODE_IMAGE_PULL_FAILURE,
        EventType.NODE_CNI_FAILURE,
        EventType.NODE_DISK_PRESSURE,
    ],
)
def test_node_not_ready_generators(event_type: EventType) -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(event_type), Random(0))
    assert result is not None
    assert result.topic is Topic.NODE_EVENTS
    assert result.message.correlation_id == "correlation-1"
    assert state.nodes["node-0"].health_state is NodeHealthState.NOT_READY


# --- GPU-level ---


@pytest.mark.parametrize(
    ("event_type", "expected_health"),
    [
        (EventType.GPU_THERMAL_THROTTLING, GpuHealthState.THROTTLING),
        (EventType.GPU_ECC_UNCORRECTABLE, GpuHealthState.DEGRADED),
        (EventType.GPU_XID_ERROR, GpuHealthState.DEGRADED),
        (EventType.GPU_NVLINK_DEGRADED, GpuHealthState.DEGRADED),
        (EventType.GPU_DRIVER_CRASH, GpuHealthState.FAILED),
    ],
)
def test_gpu_generators_set_health_state(event_type: EventType, expected_health: GpuHealthState) -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(event_type), Random(0))
    assert result is not None
    assert result.topic is Topic.GPU_METRICS
    assert state.gpus[result.message.payload.id].health_state is expected_health


def test_gpu_ecc_generator_increments_counter() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.GPU_ECC_UNCORRECTABLE), Random(0))
    assert result is not None
    assert state.gpus[result.message.payload.id].ecc_uncorrectable_count == 1


def test_gpu_xid_generator_increments_counter() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.GPU_XID_ERROR), Random(0))
    assert result is not None
    assert state.gpus[result.message.payload.id].xid_error_count == 1


# --- Job-level ---


@pytest.mark.parametrize(
    "event_type",
    [EventType.JOB_OOM_KILL, EventType.JOB_NCCL_TIMEOUT, EventType.JOB_PREEMPTED],
)
def test_job_failure_generators_fail_a_running_job(event_type: EventType) -> None:
    state = state_with_running_job()
    result = generate(state, fired_event(event_type), Random(0))
    assert result is not None
    assert result.topic is Topic.JOB_EVENTS
    assert state.jobs["job-1"].state is JobState.FAILED
    assert state.jobs["job-1"].failure_reason is not None


def test_job_straggler_generator_flags_without_failing() -> None:
    state = state_with_running_job()
    result = generate(state, fired_event(EventType.JOB_STRAGGLER), Random(0))
    assert result is not None
    assert result.topic is Topic.JOB_EVENTS
    assert state.jobs["job-1"].state is JobState.RUNNING


def test_job_checkpoint_corrupt_generator_sets_flag() -> None:
    state = state_with_running_job()
    result = generate(state, fired_event(EventType.JOB_CHECKPOINT_CORRUPT), Random(0))
    assert result is not None
    assert state.jobs["job-1"].checkpoint_corrupt is True


def test_job_generators_noop_without_a_running_job() -> None:
    state = build_cluster_state()
    assert generate(state, fired_event(EventType.JOB_OOM_KILL), Random(0)) is None


# --- Capacity-level ---


def test_capacity_fragmentation_emits_queueing_delay() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.CAPACITY_FRAGMENTATION), Random(0))
    assert result is not None
    assert result.topic is Topic.SCHEDULER_EVENTS
    assert result.message.payload.type is SchedulerEventType.QUEUEING_DELAY
    assert result.message.payload.delay_seconds is not None


def test_capacity_reserved_idle_emits_placement_event() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.CAPACITY_RESERVED_IDLE), Random(0))
    assert result is not None
    assert result.topic is Topic.SCHEDULER_EVENTS
    assert result.message.payload.type is SchedulerEventType.PLACEMENT


def test_node_drained_generator_marks_node_draining() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.NODE_DRAINED), Random(0))
    assert result is not None
    assert result.topic is Topic.NODE_EVENTS
    assert state.nodes["node-0"].health_state is NodeHealthState.DRAINING


def test_node_health_check_removed_generator_cordons_node() -> None:
    state = build_cluster_state()
    result = generate(state, fired_event(EventType.NODE_HEALTH_CHECK_REMOVED), Random(0))
    assert result is not None
    assert result.topic is Topic.NODE_EVENTS
    assert state.nodes["node-0"].health_state is NodeHealthState.CORDONED


# --- Baseline job lifecycle: create -> run -> complete ---


def test_job_lifecycle_creates_then_completes_jobs() -> None:
    state = build_cluster_state()
    lifecycle = JobLifecycle(
        arrival_probability=1.0, completion_probability=1.0, random_generator=Random(0)
    )
    lifecycle.step(state)
    assert any(job.state is JobState.PENDING for job in state.jobs.values())
    for _ in range(5):
        lifecycle.step(state)
    assert any(job.state is JobState.COMPLETED for job in state.jobs.values())


def test_jobs_are_only_placed_on_ready_nodes() -> None:
    state = build_cluster_state()
    for node_id, node in state.nodes.items():
        if node_id != "node-0":
            node.health_state = NodeHealthState.NOT_READY
    lifecycle = JobLifecycle(arrival_probability=1.0, random_generator=Random(0))
    for _ in range(10):
        lifecycle.step(state)
    running = [job for job in state.jobs.values() if job.state is JobState.RUNNING]
    assert running
    assert all(job.assigned_node_ids == ["node-0"] for job in running)


def test_jobs_stay_pending_when_no_node_is_ready() -> None:
    state = build_cluster_state()
    for node in state.nodes.values():
        node.health_state = NodeHealthState.NOT_READY
    lifecycle = JobLifecycle(arrival_probability=1.0, random_generator=Random(0))
    for _ in range(5):
        lifecycle.step(state)
    assert state.jobs
    assert all(job.state is JobState.PENDING for job in state.jobs.values())


def test_failed_job_records_a_finish_time() -> None:
    state = state_with_running_job()
    generate(state, fired_event(EventType.JOB_OOM_KILL), Random(0))
    assert state.jobs["job-1"].state is JobState.FAILED
    assert state.jobs["job-1"].finished_at is not None   # a terminal state always carries a time
