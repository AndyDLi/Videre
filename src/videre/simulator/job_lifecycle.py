"""
Simulates the normal, healthy lifecycle of jobs in a cluster.
Most jobs go PENDING -> RUNNING -> COMPLETED.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from random import Random
from uuid import uuid4

from videre.event_types import LifecycleEventType
from videre.models import Job, JobState, ResourceRequest

from .cluster_state import ClusterState
from .generators import GeneratedEvent, make_job_message
from .materialization import Materializer

logger = logging.getLogger("videre.simulator.job_lifecycle")


class JobLifecycle:
    def __init__(
        self,
        *,
        arrival_probability: float = 0.2,
        completion_probability: float = 0.05,
        random_generator: Random | None = None,
        materializer: Materializer | None = None,
    ) -> None:
        self._arrival_probability = arrival_probability
        self._completion_probability = completion_probability
        self._random_generator = random_generator if random_generator is not None else Random()
        self._materializer = materializer
        self._run_token = uuid4().hex[:8]
        self._job_counter = 0
    
    def step(self, state: ClusterState) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []
        
        for job in [job for job in state.jobs.values() if job.state is JobState.RUNNING]:
            if self._random_generator.random() < self._completion_probability:
                job.state = JobState.COMPLETED
                job.finished_at = datetime.now(UTC)
                if self._materializer is not None and job.pod_name is not None:
                    self._materializer.signal_outcome(job.pod_name, "complete")
                events.append(make_job_message(LifecycleEventType.JOB_COMPLETED.value, str(uuid4()), job))

        schedulable = state.schedulable_node_ids()
        for job in [job for job in state.jobs.values() if job.state is JobState.PENDING]:
            if not schedulable:
                break
            node_id = self._random_generator.choice(schedulable)
            job.assigned_node_ids = [node_id]
            job.pod_name = self._materialize(job, node_id)
            job.state = JobState.RUNNING
            job.started_at = datetime.now(UTC)
            events.append(make_job_message(LifecycleEventType.JOB_RUNNING.value, str(uuid4()), job))

        if self._random_generator.random() < self._arrival_probability:
            events.append(self._create_job(state))
        return events
    
    def _materialize(self, job: Job, node_id: str) -> str | None:
        if self._materializer is None:
            return None
        
        try:
            return self._materializer.materialize(job, node_id)
        except Exception as error:    # a Kubernetes API problem degrades the run only
            logger.warning("materialization failed", extra={"job": job.id, "error": str(error)})
            return None

    def _create_job(self, state: ClusterState) -> GeneratedEvent:
        self._job_counter += 1
        cluster_id = next(iter(state.clusters))
        job = Job(
            id=f"job-{self._run_token}-{self._job_counter}",
            cluster_id=cluster_id,
            resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1),
        )
        state.jobs[job.id] = job
        return make_job_message(LifecycleEventType.JOB_PENDING.value, str(uuid4()), job)
