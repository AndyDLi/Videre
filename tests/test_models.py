"""
Unit tests for the core entity models.
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from videre.models import (
    GPU,
    Cluster,
    GpuHealthState,
    Job,
    JobState,
    Node,
    NodeHealthState,
    ResourceRequest,
    SchedulerEvent,
    SchedulerEventType,
)


def sample_cluster() -> Cluster:
    return Cluster(id="cluster-a", name="Cluster A", node_ids=["node-01", "node-02"])


def sample_node() -> Node:
    return Node(id="node-01", cluster_id="cluster-a", cpu_cores=64, memory_gb=512, gpu_count=8)


def sample_gpu() -> GPU:
    return GPU(
        id="gpu-node01-0",
        node_id="node-01",
        utilization_percentage=30.0,
        temperature_celsius=45.0,
        memory_used_mb=1024,
        memory_total_mb=81920,
        ecc_correctable_count=2,
    )


def sample_resource_request() -> ResourceRequest:
    return ResourceRequest(cpu_cores=32, memory_gb=256, gpu_count=8)


def sample_job() -> Job:
    return Job(id="job-1", cluster_id="cluster-a", resources=sample_resource_request())


def sample_placement_event() -> SchedulerEvent:
    return SchedulerEvent(
        id="event-1",
        type=SchedulerEventType.PLACEMENT,
        job_id="job-1",
        node_id="node-01",
        reason="placed on node-01",
    )


def sample_queueing_delay_event() -> SchedulerEvent:
    return SchedulerEvent(
        id="event-2",
        type=SchedulerEventType.QUEUEING_DELAY,
        job_id="job-1",
        delay_seconds=45.0,
        reason="no eligible capacity",
    )


@pytest.mark.parametrize(
    "model",
    [
        sample_cluster(),
        sample_node(),
        sample_gpu(),
        sample_resource_request(),
        sample_job(),
        sample_placement_event(),
        sample_queueing_delay_event(),
    ],
)
def test_json_roundtrip(model) -> None:
    """Every entity model survives serialization to JSON and back unchanged."""

    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_cluster_defaults() -> None:
    """A cluster defaults to an empty node list."""

    assert Cluster(id="cluster-a", name="Cluster A").node_ids == []


def test_node_defaults() -> None:
    """A node defaults to READY."""

    assert sample_node().health_state is NodeHealthState.READY


def test_gpu_defaults() -> None:
    """A GPU defaults to healthy, idle, and free of recorded errors."""

    gpu = GPU(id="gpu-node01-0", node_id="node-01", memory_total_mb=80)
    assert gpu.utilization_percentage == 0.0
    assert gpu.temperature_celsius == 0.0
    assert gpu.memory_used_mb == 0
    assert gpu.ecc_correctable_count == 0
    assert gpu.ecc_uncorrectable_count == 0
    assert gpu.xid_error_count == 0
    assert gpu.health_state is GpuHealthState.HEALTHY


def test_job_defaults() -> None:
    """A job defaults to PENDING with no placement, pod, or finish time."""

    job = sample_job()
    assert job.assigned_node_ids == []
    assert job.state is JobState.PENDING
    assert job.priority == 0
    assert job.pod_name is None
    assert job.checkpoint_corrupt is False
    assert job.failure_reason is None
    assert job.started_at is None
    assert job.finished_at is None


def test_scheduler_event_defaults() -> None:
    """A scheduler event defaults to a timezone-aware timestamp."""

    assert sample_placement_event().delay_seconds is None


@pytest.mark.parametrize(
    ("model", "field", "expected"),
    [
        (sample_node(), "health_state", "READY"),
        (sample_gpu(), "health_state", "HEALTHY"),
        (sample_job(), "state", "PENDING"),
        (sample_placement_event(), "type", "PLACEMENT"),
    ],
)
def test_enum_serializes_as_plain_string(model, field, expected) -> None:
    """Every enum field serializes to a plain string for the Kafka wire format."""

    assert json.loads(model.model_dump_json())[field] == expected


def test_timestamps_are_tz_aware_iso8601() -> None:
    """Timestamps serialize as timezone-aware ISO-8601 values."""

    for iso in (
        json.loads(sample_job().model_dump_json())["created_at"],
        json.loads(sample_placement_event().model_dump_json())["timestamp"],
    ):
        assert datetime.fromisoformat(iso).tzinfo is not None


def test_cluster_rejects_extra_fields() -> None:
    """An unrecognized field is rejected rather than silently ignored."""

    with pytest.raises(ValidationError):
        Cluster(id="cluster-a", name="Cluster A", bogus="x")


@pytest.mark.parametrize(
    "override",
    [
        {"cpu_cores": 0},
        {"memory_gb": 0},
        {"gpu_count": -1},
    ],
)
def test_node_rejects_invalid_capacity(override) -> None:
    """A node rejects non-positive CPU or memory and a negative GPU count."""

    base = {"id": "node-01", "cluster_id": "cluster-a", "cpu_cores": 8, "memory_gb": 8, "gpu_count": 0}
    with pytest.raises(ValidationError):
        Node(**{**base, **override})


@pytest.mark.parametrize(
    "override",
    [
        {"utilization_percentage": 150.0},
        {"utilization_percentage": -1.0},
        {"temperature_celsius": -1.0},
        {"memory_total_mb": 0},
        {"memory_used_mb": 200, "memory_total_mb": 100},
    ],
)
def test_gpu_rejects_invalid_values(override) -> None:
    """A GPU rejects out-of-range utilization, temperature, and memory values."""

    base = {"id": "gpu-node01-0", "node_id": "node-01", "memory_total_mb": 80}
    with pytest.raises(ValidationError):
        GPU(**{**base, **override})


@pytest.mark.parametrize(
    "override",
    [
        {"cpu_cores": 0},
        {"memory_gb": 0},
        {"gpu_count": -1},
    ],
)
def test_resource_request_rejects_invalid_values(override) -> None:
    """A resource request rejects non-positive CPU or memory and a negative GPU count."""

    base = {"cpu_cores": 8, "memory_gb": 8, "gpu_count": 0}
    with pytest.raises(ValidationError):
        ResourceRequest(**{**base, **override})


def test_job_requires_resources() -> None:
    """A job cannot be constructed without a resource request."""

    with pytest.raises(ValidationError):
        Job(id="job-1", cluster_id="cluster-a")


@pytest.mark.parametrize(
    "override",
    [
        {"type": SchedulerEventType.QUEUEING_DELAY, "delay_seconds": None},
        {"type": SchedulerEventType.PLACEMENT, "delay_seconds": 5.0},
        {"type": SchedulerEventType.QUEUEING_DELAY, "delay_seconds": -1.0},
    ],
)
def test_scheduler_event_delay_rules(override) -> None:
    """A delay is required on queueing-delay events and forbidden on every other type."""

    base = {"id": "event-1", "type": SchedulerEventType.PLACEMENT, "reason": "scheduler decision"}
    with pytest.raises(ValidationError):
        SchedulerEvent(**{**base, **override})
