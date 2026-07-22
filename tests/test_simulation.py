from random import Random
from threading import Event

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
