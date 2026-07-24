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

# --- Valid sample payloads and messages ---


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


# --- Every message survives a JSON round-trip ---


@pytest.mark.parametrize("message", sample_messages())
def test_message_json_roundtrip(message) -> None:
    assert type(message).model_validate_json(message.model_dump_json()) == message


# --- Envelope behavior ---


def test_envelope_defaults() -> None:
    message = NodeEventMessage(event_type="node.ready", payload=sample_node())
    assert message.schema_version == SCHEMA_VERSION
    assert isinstance(message.correlation_id, str) and message.correlation_id
    timestamp = json.loads(message.model_dump_json())["timestamp"]
    assert datetime.fromisoformat(timestamp).tzinfo is not None


def test_correlation_id_roundtrips_when_set() -> None:
    message = GpuMetricMessage(
        event_type="gpu.thermal_throttling",
        correlation_id="cascade-123",
        payload=sample_gpu(),
    )
    reparsed = GpuMetricMessage.model_validate_json(message.model_dump_json())
    assert reparsed.correlation_id == "cascade-123"


def test_envelope_wraps_payload() -> None:
    message = NodeEventMessage(event_type="node.ready", payload=sample_node())
    data = json.loads(message.model_dump_json())
    assert set(data) >= {"event_type", "schema_version", "timestamp", "correlation_id", "payload"}
    assert data["payload"]["id"] == "node-01"


def test_extra_envelope_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        NodeEventMessage(event_type="node.ready", payload=sample_node(), bogus="x")


def test_event_id_is_unique_per_message() -> None:
    first = NodeEventMessage(event_type="node.kubelet_down", payload=sample_node())
    second = NodeEventMessage(event_type="node.kubelet_down", payload=sample_node())
    assert first.event_id != second.event_id


def test_event_id_is_independent_of_correlation_id() -> None:
    cascade = "cascade-1"
    trigger = NodeEventMessage(event_type="node.disk_pressure", correlation_id=cascade, payload=sample_node())
    downstream = JobEventMessage(event_type="job.nccl_timeout", correlation_id=cascade, payload=sample_job())
    assert trigger.correlation_id == downstream.correlation_id
    assert trigger.event_id != downstream.event_id

# --- Partition keys ---


def test_partition_keys() -> None:
    assert node_event_key(NodeEventMessage(event_type="node.ready", payload=sample_node())) == "node-01"
    assert gpu_metric_key(GpuMetricMessage(event_type="gpu.metric", payload=sample_gpu())) == "node-01"
    assert job_event_key(JobEventMessage(event_type="job.completed", payload=sample_job())) == "job-1"
    assert scheduler_event_key(
        SchedulerEventMessage(event_type="scheduler.preemption", payload=sample_scheduler_event())
    ) == "job-1"


# --- Topic names ---


def test_topic_values() -> None:
    assert {topic.value for topic in Topic} == {
        "node-events",
        "gpu-metrics",
        "job-events",
        "scheduler-events",
    }
