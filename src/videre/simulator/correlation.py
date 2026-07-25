"""
Discrete-event failure simulator.
Produces abstract failure events.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from random import Random
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from videre.event_types import EventType


@dataclass(frozen=True)
class EventTarget:
    node_id: str
    gpu_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True)
class ScheduledEvent:
    event_type: EventType
    target: EventTarget
    fire_at: float
    correlation_id: str
    depth: int


class CorrelationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    trigger: EventType
    downstream: EventType
    probability: float = Field(ge=0.0, le=1.0)
    min_delay_seconds: float = Field(ge=0.0)
    max_delay_seconds: float = Field(ge=0.0)
    
    @model_validator(mode="after")
    def _delays_are_ordered(self) -> CorrelationRule:
        if self.min_delay_seconds > self.max_delay_seconds:
            raise ValueError("min_delay_seconds cannot exceed max_delay_seconds")
        return self


# Trigger events can probabilistically cause downstream events to occur within a time window.

CORRELATION_RULES: list[CorrelationRule] = [
    # GPU -> Job
    CorrelationRule(
        trigger=EventType.GPU_THERMAL_THROTTLING,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=0.4,
        min_delay_seconds=30.0,
        max_delay_seconds=90.0,
    ),
    CorrelationRule(
        trigger=EventType.GPU_THERMAL_THROTTLING,
        downstream=EventType.JOB_STRAGGLER,
        probability=0.35,
        min_delay_seconds=15.0,
        max_delay_seconds=60.0,
    ),
    CorrelationRule(
        trigger=EventType.GPU_ECC_UNCORRECTABLE,
        downstream=EventType.JOB_OOM_KILL,
        probability=0.6,
        min_delay_seconds=5.0,
        max_delay_seconds=30.0,
    ),
    CorrelationRule(
        trigger=EventType.GPU_DRIVER_CRASH,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=0.7,
        min_delay_seconds=1.0,
        max_delay_seconds=10.0,
    ),
    CorrelationRule(
        trigger=EventType.GPU_NVLINK_DEGRADED,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=0.5,
        min_delay_seconds=10.0,
        max_delay_seconds=45.0,
    ),

    # GPU -> GPU
    CorrelationRule(
        trigger=EventType.GPU_ECC_UNCORRECTABLE,
        downstream=EventType.GPU_XID_ERROR,
        probability=0.3,
        min_delay_seconds=5.0,
        max_delay_seconds=45.0,
    ),
    CorrelationRule(
        trigger=EventType.GPU_XID_ERROR,
        downstream=EventType.GPU_DRIVER_CRASH,
        probability=0.25,
        min_delay_seconds=5.0,
        max_delay_seconds=60.0,
    ),

    # Node -> Node
    CorrelationRule(
        trigger=EventType.NODE_DISK_PRESSURE,
        downstream=EventType.NODE_KUBELET_DOWN,
        probability=0.3,
        min_delay_seconds=20.0,
        max_delay_seconds=60.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_KUBELET_DOWN,
        downstream=EventType.NODE_HEALTH_CHECK_REMOVED,
        probability=0.3,
        min_delay_seconds=60.0,
        max_delay_seconds=180.0,
    ),

    # Node -> Job
    CorrelationRule(
        trigger=EventType.NODE_KUBELET_DOWN,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=0.5,
        min_delay_seconds=5.0,
        max_delay_seconds=20.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_CNI_FAILURE,
        downstream=EventType.JOB_NCCL_TIMEOUT,
        probability=0.55,
        min_delay_seconds=5.0,
        max_delay_seconds=30.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_DISK_PRESSURE,
        downstream=EventType.JOB_CHECKPOINT_CORRUPT,
        probability=0.35,
        min_delay_seconds=10.0,
        max_delay_seconds=40.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_DRAINED,
        downstream=EventType.JOB_PREEMPTED,
        probability=0.4,
        min_delay_seconds=10.0,
        max_delay_seconds=30.0,
    ),

    # Node -> Capacity
    CorrelationRule(
        trigger=EventType.NODE_DRAINED,
        downstream=EventType.CAPACITY_RESERVED_IDLE,
        probability=0.5,
        min_delay_seconds=30.0,
        max_delay_seconds=120.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_HEALTH_CHECK_REMOVED,
        downstream=EventType.CAPACITY_FRAGMENTATION,
        probability=0.5,
        min_delay_seconds=5.0,
        max_delay_seconds=45.0,
    ),
    CorrelationRule(
        trigger=EventType.NODE_UNTOLERATED_TAINT,
        downstream=EventType.CAPACITY_FRAGMENTATION,
        probability=0.4,
        min_delay_seconds=10.0,
        max_delay_seconds=60.0,
    ),

    # Capacity -> Job
    CorrelationRule(
        trigger=EventType.CAPACITY_FRAGMENTATION,
        downstream=EventType.JOB_PREEMPTED,
        probability=0.25,
        min_delay_seconds=20.0,
        max_delay_seconds=90.0,
    ),
]


# Relative likelihood of each event type occurring independently: any failure mode can start a cascade.

BASELINE_FAILURE_WEIGHTS: dict[EventType, float] = {
    # Node-level
    EventType.NODE_KUBELET_DOWN: 0.5,
    EventType.NODE_UNTOLERATED_TAINT: 0.6,
    EventType.NODE_IMAGE_PULL_FAILURE: 2.0,
    EventType.NODE_CNI_FAILURE: 0.8,
    EventType.NODE_DISK_PRESSURE: 1.5,

    # GPU-level
    EventType.GPU_THERMAL_THROTTLING: 5.0,
    EventType.GPU_ECC_UNCORRECTABLE: 0.5,
    EventType.GPU_XID_ERROR: 1.0,
    EventType.GPU_NVLINK_DEGRADED: 0.6,
    EventType.GPU_DRIVER_CRASH: 0.3,

    # Job-level
    EventType.JOB_OOM_KILL: 4.0,
    EventType.JOB_NCCL_TIMEOUT: 0.5,
    EventType.JOB_STRAGGLER: 3.0,
    EventType.JOB_CHECKPOINT_CORRUPT: 0.4,
    EventType.JOB_PREEMPTED: 2.0,

    # Capacity-level
    EventType.CAPACITY_FRAGMENTATION: 1.0,
    EventType.NODE_DRAINED: 0.5,
    EventType.CAPACITY_RESERVED_IDLE: 0.8,
    EventType.NODE_HEALTH_CHECK_REMOVED: 0.2,
}


class CorrelationEngine:
    def __init__(
        self,
        *,
        rules: Iterable[CorrelationRule] | None = None,
        weights: dict[EventType, float] | None = None,
        baseline_failure_probability: float = 0.05,
        max_cascade_depth: int = 3,         # limits the chain of cause-and-effect events
        max_fanout_per_event: int = 2,      # limits the number of immediate downstream events one event can create
        random_generator: Random | None = None,
    ) -> None:
        self._rules_by_trigger: dict[EventType, list[CorrelationRule]] = {}
        for rule in CORRELATION_RULES if rules is None else rules:
            self._rules_by_trigger.setdefault(rule.trigger, []).append(rule)
        self._weights = dict(BASELINE_FAILURE_WEIGHTS if weights is None else weights)
        self._baseline_failure_probability = baseline_failure_probability
        self._max_cascade_depth = max_cascade_depth
        self._max_fanout_per_event = max_fanout_per_event
        self._random = random_generator if random_generator is not None else Random()
        self._heap: list[tuple[float, int, ScheduledEvent]] = []
        self._sequence = 0
    
    def schedule(self, event: ScheduledEvent) -> None:
        heapq.heappush(self._heap, (event.fire_at, self._sequence, event))
        self._sequence += 1
    
    def maybe_emit_baseline(self, target: EventTarget, now: float) -> ScheduledEvent | None:
        """Occasionally inject an uncorrelated failure event for a given target."""
        
        if self._random.random() >= self._baseline_failure_probability:
            return None
        
        population = list(self._weights)
        weights = [self._weights[event_type] for event_type in population]
        event_type = self._random.choices(population, weights=weights, k=1)[0]
        event = ScheduledEvent(event_type, target, now, str(uuid4()), depth=0)
        self.schedule(event)
        return event
    
    def fire_due(self, now: float) -> list[ScheduledEvent]:
        fired: list[ScheduledEvent] = []
        while self._heap and self._heap[0][0] <= now:
            event = heapq.heappop(self._heap)[2]
            fired.append(event)
            self._spawn_correlated(event)
        return fired
    
    def _spawn_correlated(self, event: ScheduledEvent) -> None:
        if event.depth >= self._max_cascade_depth:
            return
        
        fanout = 0
        for rule in self._rules_by_trigger.get(event.event_type, ()):
            if fanout >= self._max_fanout_per_event:
                break
            
            if self._random.random() < rule.probability:
                delay = self._random.uniform(rule.min_delay_seconds, rule.max_delay_seconds)
                self.schedule(
                    ScheduledEvent(
                        event_type=rule.downstream,
                        target=EventTarget(node_id=event.target.node_id),
                        fire_at=event.fire_at + delay,
                        correlation_id=event.correlation_id,
                        depth=event.depth + 1,
                    )
                )
                fanout += 1
    
    @property
    def pending_count(self) -> int:
        return len(self._heap)
