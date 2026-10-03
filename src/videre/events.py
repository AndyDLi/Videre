"""
Kafka message schema.
Each message is a JSON object.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models.entities import GPU, Job, Node, SchedulerEvent

SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 2


class Topic(StrEnum):
    NODE_EVENTS = "node-events"
    GPU_METRICS = "gpu-metrics"
    JOB_EVENTS = "job-events"
    SCHEDULER_EVENTS = "scheduler-events"


class SimulationRun(BaseModel):
    """One immutable identity shared by every event from a fresh simulator."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    cluster_id: str = Field(min_length=1, max_length=64)
    started_at: AwareDatetime

    @field_validator("started_at")
    @classmethod
    def _normalize_start(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class EventMessage[PayloadT: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))    # unique per message; idempotent key for consumers
    event_type: str
    schema_version: int = SCHEMA_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))   # shared identifier for messages in a workflow
    payload: PayloadT
    simulation_run: SimulationRun | None = None

    @model_validator(mode="after")
    def _validate_run_contract(self) -> EventMessage[PayloadT]:
        if self.schema_version == SCHEMA_VERSION:
            if self.simulation_run is not None:
                raise ValueError("schema version 1 cannot carry a simulation run")
        elif self.schema_version == RUN_SCHEMA_VERSION:
            if self.simulation_run is None:
                raise ValueError("schema version 2 requires a simulation run")
            if isinstance(self.payload, (Node, Job)) and self.payload.cluster_id != self.simulation_run.cluster_id:
                raise ValueError("payload cluster_id must match simulation run cluster_id")
        else:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        return self


NodeEventMessage = EventMessage[Node]
GpuMetricMessage = EventMessage[GPU]
JobEventMessage = EventMessage[Job]
SchedulerEventMessage = EventMessage[SchedulerEvent]


TOPIC_MESSAGE_TYPES: dict[Topic, type[EventMessage[Any]]] = {
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
