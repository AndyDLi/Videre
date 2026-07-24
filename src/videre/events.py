"""
Kafka message schema.
Each message is a JSON object.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models.entities import GPU, Job, Node, SchedulerEvent

SCHEMA_VERSION = 1


class Topic(StrEnum):
    NODE_EVENTS = "node-events"
    GPU_METRICS = "gpu-metrics"
    JOB_EVENTS = "job-events"
    SCHEDULER_EVENTS = "scheduler-events"


class EventMessage[PayloadT: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))    # unique per message; idempotent key for consumers
    event_type: str
    schema_version: int = SCHEMA_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))   # shared identifier for messages in a workflow
    payload: PayloadT


NodeEventMessage = EventMessage[Node]
GpuMetricMessage = EventMessage[GPU]
JobEventMessage = EventMessage[Job]
SchedulerEventMessage = EventMessage[SchedulerEvent]


TOPIC_MESSAGE_TYPES: dict[Topic, type[BaseModel]] = {
    Topic.NODE_EVENTS: NodeEventMessage,
    Topic.GPU_METRICS: GpuMetricMessage,
    Topic.JOB_EVENTS: JobEventMessage,
    Topic.SCHEDULER_EVENTS: SchedulerEventMessage,
}


# Partition keys: Kafka hashes the key to determine which partition a message goes to.
# Events with the same key always go to the same partition, which preserves order for that key.
# Example: all events for a given Node go to the same partition, so they are processed in order.

def node_event_key(message: NodeEventMessage) -> str:
    return message.payload.id


def gpu_metric_key(message: GpuMetricMessage) -> str:
    return message.payload.node_id


def job_event_key(message: JobEventMessage) -> str:
    return message.payload.id


def scheduler_event_key(message: SchedulerEventMessage) -> str:
    return message.payload.job_id or message.payload.node_id or message.payload.id
