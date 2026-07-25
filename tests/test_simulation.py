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
    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert Topic.GPU_METRICS in {event.topic for event in publisher.published}


def test_tick_emits_job_lifecycle_events() -> None:
    simulator = Simulator(random_generator=Random(0), job_arrival_probability=1.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert Topic.JOB_EVENTS in {event.topic for event in publisher.published}


def test_published_messages_are_serializable() -> None:
    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)
    assert publisher.published
    for event in publisher.published:
        assert event.message.model_dump_json()


def test_run_flushes_on_stop() -> None:
    simulator = Simulator(random_generator=Random(0))
    publisher = FakePublisher()
    stop_event = Event()
    stop_event.set()
    simulator.run(publisher, stop_event=stop_event, tick_interval_seconds=0.0)
    assert publisher.flushed


def test_tick_emits_node_state_periodically() -> None:
    # without this a consumer joining mid-stream never learns a healthy node's capacity, since
    # nodes otherwise publish only on failure or recovery
    simulator = Simulator(random_generator=Random(0), node_count=4, telemetry_interval_seconds=0.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)

    node_states = [
        event for event in publisher.published
        if event.topic is Topic.NODE_EVENTS
        and event.message.event_type == LifecycleEventType.NODE_STATE.value
    ]
    assert len(node_states) == 4                                  # every node, every interval
    payload = node_states[0].message.payload
    assert payload.cpu_cores > 0 and payload.cluster_id           # carries real capacity, not a stub


def test_node_state_is_not_emitted_between_telemetry_intervals() -> None:
    simulator = Simulator(random_generator=Random(0), telemetry_interval_seconds=1000.0)
    publisher = FakePublisher()
    simulator.tick(publisher, now=0.0)     # first tick always emits
    published_after_first = len(publisher.published)
    simulator.tick(publisher, now=1.0)     # well inside the interval

    emitted = [
        event for event in publisher.published[published_after_first:]
        if event.message.event_type == LifecycleEventType.NODE_STATE.value
    ]
    assert emitted == []
