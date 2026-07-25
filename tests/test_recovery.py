from random import Random

from videre.event_types import EventType, LifecycleEventType
from videre.events import Topic
from videre.models import GpuHealthState, NodeHealthState
from videre.simulator.cluster_state import build_cluster_state
from videre.simulator.correlation import EventTarget, ScheduledEvent
from videre.simulator.generators import generate
from videre.simulator.recovery import IDLE_TEMPERATURE_CELSIUS, HealthRecovery


def test_recovery_returns_unhealthy_node_to_ready_and_emits_event() -> None:
    state = build_cluster_state()
    state.nodes["node-0"].health_state = NodeHealthState.NOT_READY
    recovery = HealthRecovery(node_recovery_probability=1.0, random_generator=Random(0))

    events = recovery.step(state)

    assert state.nodes["node-0"].health_state is NodeHealthState.READY
    node_event = next(event for event in events if event.topic is Topic.NODE_EVENTS)
    assert node_event.message.event_type == LifecycleEventType.NODE_RECOVERED.value


def test_recovery_returns_unhealthy_gpu_to_healthy_and_cools_it() -> None:
    state = build_cluster_state()
    gpu = state.gpus["gpu-0-0"]
    gpu.health_state = GpuHealthState.THROTTLING
    gpu.temperature_celsius = 92.0
    gpu.ecc_uncorrectable_count = 3
    recovery = HealthRecovery(gpu_recovery_probability=1.0, random_generator=Random(0))

    events = recovery.step(state)

    assert gpu.health_state is GpuHealthState.HEALTHY
    assert gpu.temperature_celsius == IDLE_TEMPERATURE_CELSIUS
    assert gpu.ecc_uncorrectable_count == 3
    assert any(event.topic is Topic.GPU_METRICS for event in events)


def test_recovery_leaves_healthy_entities_untouched() -> None:
    state = build_cluster_state()
    recovery = HealthRecovery(
        node_recovery_probability=1.0, gpu_recovery_probability=1.0, random_generator=Random(0)
    )
    assert recovery.step(state) == []


def test_zero_probability_never_recovers() -> None:
    state = build_cluster_state()
    state.nodes["node-0"].health_state = NodeHealthState.NOT_READY
    recovery = HealthRecovery(
        node_recovery_probability=0.0, gpu_recovery_probability=0.0, random_generator=Random(0)
    )
    assert recovery.step(state) == []
    assert state.nodes["node-0"].health_state is NodeHealthState.NOT_READY


def test_failures_and_recovery_reach_a_mixed_steady_state() -> None:
    state = build_cluster_state()
    random_generator = Random(1)
    recovery = HealthRecovery(node_recovery_probability=0.02, random_generator=random_generator)
    seen_ready = seen_not_ready = False
    for _ in range(2000):
        if random_generator.random() < 0.05:
            target = EventTarget(node_id=random_generator.choice(state.node_ids()))
            generate(state, ScheduledEvent(EventType.NODE_KUBELET_DOWN, target, 0.0, "c", 0), random_generator)
        recovery.step(state)
        states = {node.health_state for node in state.nodes.values()}
        seen_ready = seen_ready or NodeHealthState.READY in states
        seen_not_ready = seen_not_ready or NodeHealthState.NOT_READY in states
    assert seen_ready and seen_not_ready
