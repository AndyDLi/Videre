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

# --- Valid sample entities ---


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


# --- Every entity survives a JSON round-trip ---


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
    assert type(model).model_validate_json(model.model_dump_json()) == model


# --- Every entity has its expected defaults ---


def test_cluster_defaults() -> None:
    assert Cluster(id="cluster-a", name="Cluster A").node_ids == []


def test_node_defaults() -> None:
    assert sample_node().health_state is NodeHealthState.READY


def test_gpu_defaults() -> None:
    gpu = GPU(id="gpu-node01-0", node_id="node-01", memory_total_mb=80)
    assert gpu.utilization_percentage == 0.0
    assert gpu.temperature_celsius == 0.0
    assert gpu.memory_used_mb == 0
    assert gpu.ecc_correctable_count == 0
    assert gpu.ecc_uncorrectable_count == 0
    assert gpu.xid_error_count == 0
    assert gpu.health_state is GpuHealthState.HEALTHY


def test_job_defaults() -> None:
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
    assert sample_placement_event().delay_seconds is None


# --- Every enum field serializes to a plain string ---


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
    assert json.loads(model.model_dump_json())[field] == expected


def test_timestamps_are_tz_aware_iso8601() -> None:
    for iso in (
        json.loads(sample_job().model_dump_json())["created_at"],
        json.loads(sample_placement_event().model_dump_json())["timestamp"],
    ):
        assert datetime.fromisoformat(iso).tzinfo is not None


# --- Every entity rejects extra and invalid fields ---


def test_cluster_rejects_extra_fields() -> None:
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
    base = {"cpu_cores": 8, "memory_gb": 8, "gpu_count": 0}
    with pytest.raises(ValidationError):
        ResourceRequest(**{**base, **override})


def test_job_requires_resources() -> None:
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
    base = {"id": "event-1", "type": SchedulerEventType.PLACEMENT, "reason": "scheduler decision"}
    with pytest.raises(ValidationError):
        SchedulerEvent(**{**base, **override})
