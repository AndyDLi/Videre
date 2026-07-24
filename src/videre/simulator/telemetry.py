"""
Routine GPU telemetry between failures. Updates the GPU's utilization,
temperature, and memory usage to an appropriate random value.
"""

from __future__ import annotations

from random import Random

from videre.models import GPU, GpuHealthState, JobState

from .cluster_state import ClusterState

IDLE_TEMPERATURE_CELSIUS = 38.0
THROTTLE_TEMPERATURE_CELSIUS = 90.0
_DRIFT_RATE = 0.4


def advance_gpu_telemetry(state: ClusterState, random_generator: Random) -> None:
    running_node_ids = {
        node_id
        for job in state.jobs.values()
        if job.state is JobState.RUNNING
        for node_id in job.assigned_node_ids
    }

    for gpu in state.gpus.values():
        target = _target_utilization(gpu, gpu.node_id in running_node_ids, random_generator)
        utilization = gpu.utilization_percentage + (target - gpu.utilization_percentage) * _DRIFT_RATE
        gpu.utilization_percentage = min(100.0, max(0.0, round(utilization, 1)))

        temperature = IDLE_TEMPERATURE_CELSIUS + gpu.utilization_percentage * 0.45
        if gpu.health_state is GpuHealthState.THROTTLING:
            temperature = max(temperature, THROTTLE_TEMPERATURE_CELSIUS)
        gpu.temperature_celsius = round(temperature, 1)

        used_fraction = 0.05 + 0.008 * gpu.utilization_percentage
        gpu.memory_used_mb = min(gpu.memory_total_mb, int(gpu.memory_total_mb * used_fraction))


def _target_utilization(gpu: GPU, node_is_busy: bool, random_generator: Random) -> float:
    if gpu.health_state is GpuHealthState.FAILED:
        return 0.0
    if not node_is_busy:
        return random_generator.uniform(0.0, 12.0)
    if gpu.health_state is GpuHealthState.THROTTLING:
        return random_generator.uniform(35.0, 60.0)
    if gpu.health_state is GpuHealthState.DEGRADED:
        return random_generator.uniform(55.0, 85.0)
    return random_generator.uniform(75.0, 98.0)
