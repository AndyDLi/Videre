from random import Random

from videre.models import Job, JobState, ResourceRequest
from videre.simulator.cluster_state import build_cluster_state
from videre.simulator.job_lifecycle import JobLifecycle
from videre.simulator.materializer import (
    MATERIALIZED_LABEL,
    SIMULATED_NODE_LABEL,
    build_materialized_job,
)


def sample_job() -> Job:
    return Job(
        id="job-1",
        cluster_id="cluster-a",
        resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1)
    )


def test_build_materialized_job_carries_simulated_labels_and_caps() -> None:
    job = build_materialized_job(sample_job(), "node-2")
    assert job.metadata.name == "sim-job-1"
    assert job.metadata.labels[SIMULATED_NODE_LABEL] == "node-2"
    assert job.metadata.labels[MATERIALIZED_LABEL] == "true"
    assert job.spec.backoff_limit == 0
    assert job.spec.ttl_seconds_after_finished == 300
    assert job.spec.active_deadline_seconds == 120
    container = job.spec.template.spec.containers[0]
    assert container.resources.limits["memory"] == "32Mi"


class FakeMaterializer:
    def __init__(self) -> None:
        self.materialized: list[tuple[str, str]] = []
        self.outcomes: list[tuple[str, str]] = []

    def materialize(self, job: Job, node_id: str) -> str:
        self.materialized.append((job.id, node_id))
        return f"pod-{job.id}"

    def signal_outcome(self, pod_name: str, outcome: str) -> None:
        self.outcomes.append((pod_name, outcome))


class FailingMaterializer(FakeMaterializer):
    def materialize(self, job: Job, node_id: str) -> str:
        raise RuntimeError("kubernetes api unavailable")


def test_job_lifecycle_materializes_on_run_and_signals_on_complete() -> None:
    state = build_cluster_state()
    materializer = FakeMaterializer()
    lifecycle = JobLifecycle(
        arrival_probability=1.0, completion_probability=1.0,
        random_generator=Random(0), materializer=materializer,
    )
    for _ in range(4):
        lifecycle.step(state)
    assert materializer.materialized
    running_job_id = materializer.materialized[0][0]
    assert state.jobs[running_job_id].pod_name == f"pod-{running_job_id}"
    assert ("pod-" + running_job_id, "complete") in materializer.outcomes


def test_job_lifecycle_survives_a_failing_materializer() -> None:
    state = build_cluster_state()
    lifecycle = JobLifecycle(
        arrival_probability=1.0, completion_probability=1.0,
        random_generator=Random(0), materializer=FailingMaterializer(),
    )
    for _ in range(4):
        lifecycle.step(state)
    running_jobs = [job for job in state.jobs.values() if job.state is not JobState.PENDING]
    assert running_jobs
    assert all(job.pod_name is None for job in running_jobs)


def test_job_ids_do_not_repeat_across_simulator_restarts() -> None:
    first_run_state, second_run_state = build_cluster_state(), build_cluster_state()
    for state in (first_run_state, second_run_state):
        lifecycle = JobLifecycle(arrival_probability=1.0, random_generator=Random(0))
        for _ in range(3):
            lifecycle.step(state)
    assert set(first_run_state.jobs) & set(second_run_state.jobs) == set()
