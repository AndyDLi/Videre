from random import Random

from videre.models import Job, ResourceRequest
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
    assert job.spec.active_deadline_seconds == 1800
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
