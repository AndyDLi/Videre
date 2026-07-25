"""
Enforce recovery of unhealthy nodes and GPUs back to service.
"""

from __future__ import annotations

from random import Random
from uuid import uuid4

from videre.event_types import LifecycleEventType
from videre.models import GpuHealthState, NodeHealthState

from .cluster_state import ClusterState
from .generators import GeneratedEvent, make_gpu_message, make_node_message
from .telemetry import IDLE_TEMPERATURE_CELSIUS


class HealthRecovery:
    def __init__(
        self,
        *,
        node_recovery_probability: float = 0.005,
        gpu_recovery_probability: float = 0.01,
        random_generator: Random | None = None,
    ) -> None:
        self._node_recovery_probability = node_recovery_probability
        self._gpu_recovery_probability = gpu_recovery_probability
        self._random_generator = random_generator if random_generator is not None else Random()

    def step(self, state: ClusterState) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []

        for node in state.nodes.values():
            if node.health_state is NodeHealthState.READY:
                continue
            
            if self._random_generator.random() >= self._node_recovery_probability:
                continue
            
            node.health_state = NodeHealthState.READY
            events.append(make_node_message(LifecycleEventType.NODE_RECOVERED.value, str(uuid4()), node))

        for gpu in state.gpus.values():
            if gpu.health_state is GpuHealthState.HEALTHY:
                continue
            
            if self._random_generator.random() >= self._gpu_recovery_probability:
                continue
            
            gpu.health_state = GpuHealthState.HEALTHY
            gpu.temperature_celsius = IDLE_TEMPERATURE_CELSIUS
            events.append(make_gpu_message(LifecycleEventType.GPU_RECOVERED.value, str(uuid4()), gpu))

        return events
