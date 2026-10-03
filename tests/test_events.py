"""
Unit tests for the event message envelopes and their payloads.
"""


import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from videre.events import (
    SCHEMA_VERSION,
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    Topic,
    gpu_metric_key,
    job_event_key,
    node_event_key,
    scheduler_event_key,
)
from videre.models import GPU, Job, Node, ResourceRequest, SchedulerEvent, SchedulerEventType


def sample_node() -> Node:
    return Node(id="node-01", cluster_id="cluster-a", cpu_cores=64, memory_gb=512, gpu_count=8)


def sample_gpu() -> GPU:
    return GPU(id="gpu-node01-0", node_id="node-01", memory_total_mb=81920)


def sample_job() -> Job:
    return Job(
        id="job-1",
        cluster_id="cluster-a",
        resources=ResourceRequest(cpu_cores=32, memory_gb=256, gpu_count=8),
    )


def sample_scheduler_event() -> SchedulerEvent:
    return SchedulerEvent(
        id="event-1",
        type=SchedulerEventType.PREEMPTION,
        job_id="job-1",
        node_id="node-01",
        reason="preempted by higher-priority job",
    )


def sample_messages() -> list[object]:
    return [
        NodeEventMessage(event_type="node.ready", payload=sample_node()),
        GpuMetricMessage(event_type="gpu.metric", payload=sample_gpu()),
        JobEventMessage(event_type="job.completed", payload=sample_job()),
        SchedulerEventMessage(event_type="scheduler.preemption", payload=sample_scheduler_event()),
    ]


@pytest.mark.parametrize("message", sample_messages())
def test_message_json_roundtrip(message) -> None:
    """Every topic's message survives serialization to JSON and back unchanged."""

    assert type(message).model_validate_json(message.model_dump_json()) == message


def test_envelope_defaults() -> None:
    """A new envelope carries the schema version, a correlation id, and a timezone-aware timestamp."""

    message = NodeEventMessage(event_type="node.ready", payload=sample_node())
    assert message.schema_version == SCHEMA_VERSION
    assert isinstance(message.correlation_id, str) and message.correlation_id
    timestamp = json.loads(message.model_dump_json())["timestamp"]
    assert datetime.fromisoformat(timestamp).tzinfo is not None


def test_correlation_id_roundtrips_when_set() -> None:
    """An explicitly set correlation id survives serialization, so a cascade stays linked."""

    message = GpuMetricMessage(
        event_type="gpu.thermal_throttling",
        correlation_id="cascade-123",
        payload=sample_gpu(),
    )
    reparsed = GpuMetricMessage.model_validate_json(message.model_dump_json())
    assert reparsed.correlation_id == "cascade-123"


def test_envelope_wraps_payload() -> None:
    """The envelope exposes its metadata fields alongside the nested entity payload."""

    message = NodeEventMessage(event_type="node.ready", payload=sample_node())
    data = json.loads(message.model_dump_json())
    assert set(data) >= {"event_type", "schema_version", "timestamp", "correlation_id", "payload"}
    assert data["payload"]["id"] == "node-01"


def test_extra_envelope_fields_forbidden() -> None:
    """An unrecognized envelope field is rejected rather than silently accepted."""

    with pytest.raises(ValidationError):
        NodeEventMessage(event_type="node.ready", payload=sample_node(), bogus="x")


def test_event_id_is_unique_per_message() -> None:
    """Each message mints its own event_id, which is what makes consumer writes idempotent."""

    first = NodeEventMessage(event_type="node.kubelet_down", payload=sample_node())
    second = NodeEventMessage(event_type="node.kubelet_down", payload=sample_node())
    assert first.event_id != second.event_id


def test_event_id_is_independent_of_correlation_id() -> None:
    """Events sharing a cascade share a correlation id but keep distinct event ids."""

    cascade = "cascade-1"
    trigger = NodeEventMessage(event_type="node.disk_pressure", correlation_id=cascade, payload=sample_node())
    downstream = JobEventMessage(event_type="job.nccl_timeout", correlation_id=cascade, payload=sample_job())
    assert trigger.correlation_id == downstream.correlation_id
    assert trigger.event_id != downstream.event_id


def test_partition_keys() -> None:
    """Each topic's partition key routes an entity's events to one partition, preserving order."""

    assert node_event_key(NodeEventMessage(event_type="node.ready", payload=sample_node())) == "node-01"
    assert gpu_metric_key(GpuMetricMessage(event_type="gpu.metric", payload=sample_gpu())) == "node-01"
    assert job_event_key(JobEventMessage(event_type="job.completed", payload=sample_job())) == "job-1"
    assert scheduler_event_key(
        SchedulerEventMessage(event_type="scheduler.preemption", payload=sample_scheduler_event())
    ) == "job-1"


def test_topic_values() -> None:
    """The Topic enum names exactly the four Kafka topics the stack provisions."""

    assert {topic.value for topic in Topic} == {
        "node-events",
        "gpu-metrics",
        "job-events",
        "scheduler-events",
    }


def run_data():
    return {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "cluster_id": "cluster-a",
        "started_at": "2026-10-03T10:00:00Z",
    }


@pytest.mark.parametrize("message", sample_messages())
def test_run_envelope_roundtrips_on_every_topic(message):
    data = message.model_dump()
    data.update(schema_version=2, simulation_run=run_data())
    parsed = type(message).model_validate(data)
    assert parsed.schema_version == 2
    assert parsed.simulation_run.cluster_id == "cluster-a"
    assert type(message).model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize("version,run", [(2, None), (3, None), (0, None), (1, run_data())])
def test_envelope_rejects_incompatible_version_and_run(version, run):
    with pytest.raises(ValidationError):
        NodeEventMessage.model_validate({
            "event_type": "node.state", "payload": sample_node(),
            "schema_version": version, "simulation_run": run,
        })


@pytest.mark.parametrize("field,value", [
    ("run_id", "invalid"), ("started_at", "2026-10-03T10:00:00"),
    ("cluster_id", ""), ("cluster_id", "b" * 65),
])
def test_run_descriptor_rejects_invalid_identity_or_naive_time(field, value):
    run = run_data() | {field: value}
    with pytest.raises(ValidationError):
        NodeEventMessage.model_validate({
            "event_type": "node.state", "payload": sample_node(),
            "schema_version": 2, "simulation_run": run,
        })


@pytest.mark.parametrize("payload,message_type", [(sample_node(), NodeEventMessage), (sample_job(), JobEventMessage)])
def test_run_cluster_must_match_scoped_payload(payload, message_type):
    with pytest.raises(ValidationError):
        message_type.model_validate({
            "event_type": "state", "payload": payload,
            "schema_version": 2, "simulation_run": run_data() | {"cluster_id": "cluster-b"},
        })


def test_run_time_is_normalized_to_utc_and_descriptor_is_immutable():
    message = NodeEventMessage.model_validate({
        "event_type": "node.state", "payload": sample_node(), "schema_version": 2,
        "simulation_run": run_data() | {"started_at": "2026-10-03T12:00:00+02:00"},
    })
    assert message.simulation_run.started_at.utcoffset().total_seconds() == 0
    with pytest.raises(ValidationError):
        message.simulation_run.cluster_id = "cluster-b"


def test_legacy_wire_envelope_without_run_still_parses():
    original = NodeEventMessage(event_type="node.state", payload=sample_node())
    data = original.model_dump()
    data.pop("simulation_run", None)
    assert NodeEventMessage.model_validate(data).schema_version == 1
