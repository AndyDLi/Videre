from random import Random
from threading import Event

from videre.event_types import LifecycleEventType
from videre.events import Topic
from videre.simulator.generators import GeneratedEvent
from videre.simulator.simulation import Simulator


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[GeneratedEvent] = []
        self.flushed = False

    def publish(self, event: GeneratedEvent) -> None:
        self.published.append(event)

    def flush(self, timeout: float = 10.0) -> None:
        self.flushed = True


def test_tick_emits_gpu_telemetry() -> None:
    """A tick past the telemetry interval publishes GPU metrics."""

    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert Topic.GPU_METRICS in {event.topic for event in publisher.published}


def test_tick_emits_job_lifecycle_events() -> None:
    """A tick with a certain job arrival publishes onto the job-events topic."""

    simulator = Simulator(random_generator=Random(0), job_arrival_probability=1.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert Topic.JOB_EVENTS in {event.topic for event in publisher.published}


def test_published_messages_are_serializable() -> None:
    """Every published message serializes to JSON, so nothing can fail at the producer."""

    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert publisher.published
    for event in publisher.published:
        assert event.message.model_dump_json()


def test_run_flushes_on_stop() -> None:
    """Stopping the run loop flushes the publisher so in-flight events are not dropped."""

    simulator = Simulator(random_generator=Random(0))
    publisher = FakePublisher()
    stop_event = Event()
    stop_event.set()
    simulator.run(publisher, stop_event=stop_event, tick_interval_seconds=0.0)
    assert publisher.flushed


def test_tick_emits_node_state_periodically() -> None:
    """Every node republishes its full capacity each interval, so a consumer joining mid-stream learns it."""

    simulator = Simulator(random_generator=Random(0), node_count=4, telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)

    node_states = [
        event for event in publisher.published
        if event.topic is Topic.NODE_EVENTS
        and event.message.event_type == LifecycleEventType.NODE_STATE.value
    ]
    assert len(node_states) == 4
    payload = node_states[0].message.payload
    assert payload.cpu_cores > 0 and payload.cluster_id


def test_node_state_is_not_emitted_between_telemetry_intervals() -> None:
    """Ticks inside the telemetry interval emit no node state, bounding the message rate."""

    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=1000.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    published_after_first = len(publisher.published)
    simulator.tick(publisher, now=1.0)

    emitted = [
        event for event in publisher.published[published_after_first:]
        if event.message.event_type == LifecycleEventType.NODE_STATE.value
    ]
    assert emitted == []


def test_every_published_path_uses_one_run_across_ticks():
    from videre.event_types import EventType
    from videre.models import GpuHealthState, NodeHealthState
    from videre.simulator.correlation import EventTarget, ScheduledEvent

    simulator = Simulator(
        random_generator=Random(0), node_count=1, gpus_per_node=1,
        telemetry_interval_seconds=0, job_arrival_probability=1,
        node_recovery_probability=1, gpu_recovery_probability=1,
        baseline_failure_probability=1,
    )
    simulator._state.nodes["node-0"].health_state = NodeHealthState.NOT_READY
    simulator._state.gpus["gpu-0-0"].health_state = GpuHealthState.FAILED
    simulator._engine.schedule(ScheduledEvent(
        event_type=EventType.CAPACITY_FRAGMENTATION, target=EventTarget(node_id="node-0"),
        fire_at=0, correlation_id="capacity", depth=0,
    ))
    publisher = FakePublisher()
    for tick in range(5):
        simulator.tick(publisher, now=float(tick))
    assert {event.topic for event in publisher.published} == set(Topic)
    descriptors = [getattr(event.message, "simulation_run", None) for event in publisher.published]
    assert descriptors[0] is not None
    assert all(run == descriptors[0] for run in descriptors)
    assert all(event.message.schema_version == 2 for event in publisher.published)
    assert {"node.recovered", "gpu.recovered"} <= {event.message.event_type for event in publisher.published}
    for event in publisher.published:
        assert type(event.message).model_validate_json(event.message.model_dump_json()) == event.message


def test_fresh_simulator_mints_a_new_run_at_memory_initialization(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from videre.simulator import simulation as simulation_module

    times = iter([datetime(2026, 10, 3, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC) + timedelta(seconds=1)])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(simulation_module, "datetime", Clock, raising=False)
    runs = []
    for _ in range(2):
        simulator = Simulator(baseline_failure_probability=0, job_arrival_probability=0)
        publisher = FakePublisher()
        simulator.tick(publisher, now=0)
        runs.append(getattr(publisher.published[0].message, "simulation_run", None))
    assert runs[0] is not None and runs[1] is not None
    assert runs[0].run_id != runs[1].run_id
    assert runs[0].started_at < runs[1].started_at
