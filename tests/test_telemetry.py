from random import Random

from videre.models import GpuHealthState, Job, JobState, ResourceRequest
from videre.simulator.cluster_state import build_cluster_state
from videre.simulator.telemetry import IDLE_TEMPERATURE_CELSIUS, advance_gpu_telemetry


def _run_job_on(state, node_id: str) -> None:
    state.jobs["job-1"] = Job(
        id="job-1",
        cluster_id="cluster-a",
        assigned_node_ids=[node_id],
        state=JobState.RUNNING,
        resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1),
    )


def test_idle_node_gpus_settle_low_and_cool() -> None:
    state = build_cluster_state()
    for _ in range(20):
        advance_gpu_telemetry(state, Random(0))
    gpu = state.gpus["gpu-0-0"]
    assert gpu.utilization_percentage < 15.0
    assert gpu.temperature_celsius < 50.0


def test_busy_node_gpus_climb_and_warm() -> None:
    state = build_cluster_state()
    _run_job_on(state, "node-0")
    for _ in range(20):
        advance_gpu_telemetry(state, Random(0))
    gpu = state.gpus["gpu-0-0"]
    assert gpu.utilization_percentage > 60.0
    assert gpu.temperature_celsius > IDLE_TEMPERATURE_CELSIUS
    assert 0 < gpu.memory_used_mb <= gpu.memory_total_mb


def test_failed_gpu_reports_no_utilization() -> None:
    state = build_cluster_state()
    _run_job_on(state, "node-0")
    gpu = state.gpus["gpu-0-0"]
    gpu.health_state = GpuHealthState.FAILED
    for _ in range(20):
        advance_gpu_telemetry(state, Random(0))
    assert gpu.utilization_percentage == 0.0


def test_throttling_gpu_stays_hot_even_when_utilization_drops() -> None:
    state = build_cluster_state()
    _run_job_on(state, "node-0")
    gpu = state.gpus["gpu-0-0"]
    gpu.health_state = GpuHealthState.THROTTLING
    for _ in range(20):
        advance_gpu_telemetry(state, Random(0))
    assert gpu.temperature_celsius >= 90.0


def test_telemetry_never_leaves_the_valid_model_range() -> None:
    state = build_cluster_state()
    _run_job_on(state, "node-0")
    for _ in range(50):
        advance_gpu_telemetry(state, Random(3))
    for gpu in state.gpus.values():
        assert 0.0 <= gpu.utilization_percentage <= 100.0
        assert gpu.temperature_celsius >= 0.0
        assert 0 <= gpu.memory_used_mb <= gpu.memory_total_mb
