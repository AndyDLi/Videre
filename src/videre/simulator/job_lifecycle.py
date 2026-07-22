"""
Simulates the normal, healthy lifecycle of jobs in a cluster.
Most jobs go PENDING -> RUNNING -> COMPLETED.
"""

from __future__ import annotations

from datetime import UTC, datetime
from random import Random
from uuid import uuid4

from videre.models import Job, JobState, ResourceRequest

from .cluster_state import ClusterState
from .generators import GeneratedEvent, make_job_message


class JobLifecycle:
    def __init__(
        self,
        *,
        arrival_probability: float = 0.3,
        completion_probability: float = 0.2,
        random_generator: Random | None = None,
    ) -> None:
        self._arrival_probability = arrival_probability
        self._completion_probability = completion_probability
        self._random_generator = random_generator if random_generator is not None else Random()
        self._job_counter = 0
    
    def step(self, state: ClusterState) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []
        
        for job in [job for job in state.jobs.values() if job.state is JobState.RUNNING]:
            if self._random_generator.random() < self._completion_probability:
                job.state = JobState.COMPLETED
                job.finished_at = datetime.now(UTC)
                events.append(make_job_message("job.completed", str(uuid4()), job))
        
        for job in [job for job in state.jobs.values() if job.state is JobState.PENDING]:
            job.state = JobState.RUNNING
            job.assigned_node_ids = [self._random_generator.choice(state.node_ids())]
            job.started_at = datetime.now(UTC)
            events.append(make_job_message("job.running", str(uuid4()), job))
        
        if self._random_generator.random() < self._arrival_probability:
            events.append(self._create_job(state))
        return events
    
    def _create_job(self, state: ClusterState) -> GeneratedEvent:
        self._job_counter += 1
        cluster_id = next(iter(state.clusters))
        job = Job(
            id=f"job-{self._job_counter}",
            cluster_id=cluster_id,
            resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1),
        )
        state.jobs[job.id] = job
        return make_job_message("job.pending", str(uuid4()), job)
