"""
The simulation loop: ties together the world, engine, lifecycle, and generators
and hands every produced event to a Publisher.
"""

from __future__ import annotations

import logging
import threading
import time
from random import Random
from typing import Protocol
from uuid import uuid4

from videre.events import Topic
from videre.models import JobState

from .cluster_state import build_cluster_state
from .correlation import CorrelationEngine, EventTarget, ScheduledEvent
from .event_types import EventType
from .generators import GeneratedEvent, generate, make_gpu_message
from .job_lifecycle import JobLifecycle
from .materialization import Materializer

logger = logging.getLogger("videre.simulator")


class Publisher(Protocol):
    def publish(self, event: GeneratedEvent) -> None: ...
    def flush(self, timeout: float = 10.0) -> None: ...


class Simulator:
    def __init__(
        self,
        *,
        random_generator: Random | None = None,
        node_count: int = 4,
        gpus_per_node: int = 8,
        telemetry_interval_seconds: float = 10.0,
        baseline_failure_probability: float = 0.05,
        job_arrival_probability: float = 0.3,
        materializer: Materializer | None = None,
    ) -> None:
        self._random_generator = random_generator if random_generator is not None else Random()
        self._state = build_cluster_state(node_count=node_count, gpus_per_node=gpus_per_node)
        self._engine = CorrelationEngine(
            baseline_failure_probability=baseline_failure_probability,
            random_generator=self._random_generator,
        )
        self._materializer = materializer
        self._job_lifecycle = JobLifecycle(
            arrival_probability=job_arrival_probability,
            random_generator=self._random_generator,
            materializer=materializer,
        )
        self._telemetry_interval_seconds = telemetry_interval_seconds
        self._last_telemetry_at = float("-inf")
    
    def tick(self, publisher: Publisher, now: float) -> None:
        events: list[GeneratedEvent] = []
        events.extend(self._job_lifecycle.step(self._state))    # baseline job lifecycle events
        
        if now - self._last_telemetry_at >= self._telemetry_interval_seconds:
            events.extend(self._gpu_telemetry())    # periodic GPU metrics
            self._last_telemetry_at = now
        
        target = EventTarget(node_id=self._random_generator.choice(self._state.node_ids()))
        self._engine.maybe_emit_baseline(target, now)   # occasional failure injection
        
        for scheduled_event in self._engine.fire_due(now):  # baseline and correlated failures
            generated_event = generate(self._state, scheduled_event, self._random_generator)
            if generated_event is None:
                continue
            
            events.append(generated_event)
            self._reflect_failure(scheduled_event, generated_event)
        
        for event in events:
            publisher.publish(event)
    
    def run(self, publisher: Publisher, *, stop_event: threading.Event, tick_interval_seconds: float = 1.0) -> None:
        start = time.monotonic()
        logger.info("simulator started")
        try:
            while not stop_event.is_set():
                self.tick(publisher, now=time.monotonic() - start)
                stop_event.wait(tick_interval_seconds)
        finally:
            publisher.flush()
            logger.info("simulator stopped and flushed")
    
    def _gpu_telemetry(self) -> list[GeneratedEvent]:
        return [make_gpu_message("gpu.metric", str(uuid4()), gpu) for gpu in self._state.gpus.values()]
    
    def _reflect_failure(self, scheduled: ScheduledEvent, generated: GeneratedEvent) -> None:
        if self._materializer is None or generated.topic is not Topic.JOB_EVENTS:
            return
        
        job = self._state.jobs.get(generated.key)
        if job is None or job.state is not JobState.FAILED or job.pod_name is None:
            return
        
        outcome = "oom" if scheduled.event_type is EventType.JOB_OOM_KILL else "fail"
        self._materializer.signal_outcome(job.pod_name, outcome)
