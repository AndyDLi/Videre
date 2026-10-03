from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from videre.backend.persistence.event_mapping import (
    FAILURE_CATEGORIES,
    PLACEHOLDER_CLUSTER_ID,
    apply_event,
)
from videre.backend.persistence.retention import prune_once
from videre.database.tables import (
    Cluster,
    FailureEntityTable,
    FailureRecord,
    Gpu,
    Job,
    JobNodeAssignment,
    Node,
    SchedulerEventRecord,
)
from videre.event_types import EventType, LifecycleEventType
from videre.events import (
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    SimulationRun,
    Topic,
)
from videre.models import (
    GPU,
    GpuHealthState,
    JobState,
    NodeHealthState,
    ResourceRequest,
    SchedulerEvent,
    SchedulerEventType,
)
from videre.models import (
    Job as JobModel,
)
from videre.models import (
    Node as NodeModel,
)


def sample_node(health_state: NodeHealthState = NodeHealthState.READY) -> NodeModel:
    return NodeModel(
        id="node-0", cluster_id="cluster-a", cpu_cores=64, memory_gb=512,
        gpu_count=8, health_state=health_state,
    )


def sample_gpu() -> GPU:
    return GPU(id="gpu-0-0", node_id="node-0", memory_total_mb=81920)


def sample_job(state: JobState = JobState.RUNNING) -> JobModel:
    return JobModel(
        id="job-1", cluster_id="cluster-a", assigned_node_ids=["node-0"], state=state,
        resources=ResourceRequest(cpu_cores=8, memory_gb=64, gpu_count=1),
    )


async def _count(session, table) -> int:
    return int((await session.execute(select(func.count()).select_from(table))).scalar_one())


def test_every_failure_event_type_has_a_category() -> None:
    """Every failure event type maps to a category, so none can be persisted uncategorized."""

    assert set(FAILURE_CATEGORIES) == set(EventType)


async def test_node_event_upserts_the_node_and_records_a_failure(session) -> None:
    """A node fault upserts the node's current state and appends a failure record."""

    message = NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value,
        payload=sample_node(NodeHealthState.NOT_READY),
    )
    await apply_event(session, Topic.NODE_EVENTS, message)

    node = (await session.execute(select(Node).where(Node.id == "node-0"))).scalar_one()
    assert node.health_state == NodeHealthState.NOT_READY.value
    assert node.simulated_node_label == "node-0"

    failure = (await session.execute(select(FailureRecord))).scalar_one()
    assert failure.entity_type == FailureEntityTable.NODE.value
    assert failure.root_cause_tag == EventType.NODE_KUBELET_DOWN.value
    assert failure.resolved_at is None


async def test_gpu_metric_updates_state_without_recording_a_failure(session) -> None:
    """Routine GPU telemetry updates state without inventing a failure record."""

    gpu = sample_gpu()
    gpu.utilization_percentage = 87.5
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(event_type="gpu.metric", payload=gpu))

    stored = (await session.execute(select(Gpu).where(Gpu.id == "gpu-0-0"))).scalar_one()
    assert stored.utilization_percentage == 87.5
    assert await _count(session, FailureRecord) == 0


async def test_job_event_writes_the_job_and_its_node_assignments(session) -> None:
    """A job event writes the job row together with its node assignments."""

    message = JobEventMessage(event_type="job.running", payload=sample_job())
    await apply_event(session, Topic.JOB_EVENTS, message)

    job = (await session.execute(select(Job).where(Job.id == "job-1"))).scalar_one()
    assert job.lifecycle_state == JobState.RUNNING.value
    assert job.requested_gpu_count == 1

    assignment = (await session.execute(select(JobNodeAssignment))).scalar_one()
    assert (assignment.job_id, assignment.node_id) == ("job-1", "node-0")


async def test_failed_job_gets_a_completed_at_so_retention_can_reach_it(session) -> None:
    """A terminal job always receives a completed_at, which is what lets retention prune it later."""

    failed = sample_job(JobState.FAILED)
    assert failed.finished_at is None
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_OOM_KILL.value, payload=failed
    ))

    job = (await session.execute(select(Job).where(Job.id == "job-1"))).scalar_one()
    assert job.completed_at is not None


async def test_scheduler_event_is_persisted(session) -> None:
    """A scheduler event is appended with its delay and reason intact."""

    scheduler_event = SchedulerEvent(
        id="scheduler-1", type=SchedulerEventType.QUEUEING_DELAY, node_id="node-0",
        delay_seconds=42.0, reason="resource fragmentation delayed placement",
    )
    await apply_event(session, Topic.SCHEDULER_EVENTS, SchedulerEventMessage(
        event_type=EventType.CAPACITY_FRAGMENTATION.value, payload=scheduler_event
    ))

    stored = (await session.execute(select(SchedulerEventRecord))).scalar_one()
    assert stored.type == SchedulerEventType.QUEUEING_DELAY.value
    assert stored.delay_seconds == 42.0


async def test_reprocessing_the_same_message_creates_one_failure_record(session) -> None:
    """Redelivering a message leaves exactly one failure record, proving idempotency is real."""

    message = NodeEventMessage(
        event_type=EventType.NODE_DISK_PRESSURE.value, payload=sample_node(NodeHealthState.NOT_READY)
    )
    await apply_event(session, Topic.NODE_EVENTS, message)
    await apply_event(session, Topic.NODE_EVENTS, message)

    assert await _count(session, FailureRecord) == 1
    assert await _count(session, Node) == 1


async def test_gpu_arriving_before_its_node_creates_a_placeholder(session) -> None:
    """A GPU arriving before its node creates a placeholder rather than failing a foreign key."""

    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type="gpu.metric", payload=sample_gpu()
    ))

    node = (await session.execute(select(Node).where(Node.id == "node-0"))).scalar_one()
    assert node.cluster_id == PLACEHOLDER_CLUSTER_ID
    assert node.cpu_cores == 0

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type="node.recovered", payload=sample_node()
    ))
    session.expire_all()
    refreshed = (await session.execute(select(Node).where(Node.id == "node-0"))).scalar_one()
    assert refreshed.cluster_id == "cluster-a"
    assert refreshed.cpu_cores == 64


async def test_recovery_event_resolves_open_failures_for_that_entity_only(session) -> None:
    """Recovery resolves that entity's open failures and leaves other entities untouched."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value, payload=sample_node(NodeHealthState.NOT_READY)
    ))
    other = sample_node()
    other.id = "node-1"
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_CNI_FAILURE.value, payload=other
    ))

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type="node.recovered", payload=sample_node()
    ))

    records = (await session.execute(select(FailureRecord))).scalars().all()
    resolved = {record.entity_id: record.resolved_at for record in records}
    assert resolved["node-0"] is not None
    assert resolved["node-1"] is None


async def test_pruning_removes_aged_history_but_keeps_current_state_and_open_failures(session) -> None:
    """Pruning clears aged history while current-state rows and active incidents survive."""

    now = datetime.now(UTC)
    old = now - timedelta(days=5)

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value, timestamp=old,
        payload=sample_node(NodeHealthState.NOT_READY),
    ))
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type="job.completed", timestamp=old, payload=sample_job(JobState.COMPLETED)
    ))
    await session.flush()

    deleted = await prune_once(session, cutoff=now - timedelta(days=3))

    assert deleted["jobs"] == 1
    assert deleted["failure_records"] == 0
    assert await _count(session, Node) >= 1
    assert await _count(session, FailureRecord) == 1
    assert await _count(session, JobNodeAssignment) == 0


async def test_pruning_removes_aged_unresolved_job_failures(session) -> None:
    """A failed job never recovers, so its aged failure record is pruned by age instead of resolution."""

    now = datetime.now(UTC)
    old = now - timedelta(days=5)

    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_OOM_KILL.value, timestamp=old, payload=sample_job(JobState.FAILED)
    ))
    await session.flush()
    assert await _count(session, FailureRecord) == 1

    deleted = await prune_once(session, cutoff=now - timedelta(days=3))

    assert deleted["failure_records"] == 1
    assert await _count(session, FailureRecord) == 0


async def test_pruning_keeps_recent_unresolved_job_failures(session) -> None:
    """A recent job failure stays visible as an active incident rather than being pruned early."""

    now = datetime.now(UTC)

    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_OOM_KILL.value, timestamp=now, payload=sample_job(JobState.FAILED)
    ))
    await session.flush()

    deleted = await prune_once(session, cutoff=now - timedelta(days=3))

    assert deleted["failure_records"] == 0
    assert await _count(session, FailureRecord) == 1


async def test_pruning_removes_jobs_stranded_by_a_simulator_restart(session) -> None:
    """A restart abandons in-flight jobs with no completed_at, so they are pruned once they stop updating."""

    now = datetime.now(UTC)
    old = now - timedelta(days=5)

    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, timestamp=old,
        payload=sample_job(JobState.RUNNING),
    ))
    await session.flush()

    deleted = await prune_once(session, cutoff=now - timedelta(days=3))

    assert deleted["jobs"] == 1
    assert await _count(session, Job) == 0
    assert await _count(session, JobNodeAssignment) == 0


async def test_pruning_keeps_jobs_that_are_still_running(session) -> None:
    """A job still emitting events is left alone, however long it has been running."""

    now = datetime.now(UTC)

    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, timestamp=now,
        payload=sample_job(JobState.RUNNING),
    ))
    await session.flush()

    deleted = await prune_once(session, cutoff=now - timedelta(days=3))

    assert deleted["jobs"] == 0
    assert await _count(session, Job) == 1


async def test_reprocessing_a_scheduler_event_is_a_no_op(session) -> None:
    """Redelivering a scheduler event does not duplicate the row."""

    message = SchedulerEventMessage(
        event_type=EventType.CAPACITY_FRAGMENTATION.value,
        payload=SchedulerEvent(
            id="scheduler-1", type=SchedulerEventType.QUEUEING_DELAY, node_id="node-0",
            delay_seconds=42.0, reason="resource fragmentation delayed placement",
        ),
    )
    await apply_event(session, Topic.SCHEDULER_EVENTS, message)
    await apply_event(session, Topic.SCHEDULER_EVENTS, message)

    assert await _count(session, SchedulerEventRecord) == 1


async def test_periodic_node_state_populates_capacity_without_recording_a_failure(session) -> None:
    """Periodic node state fills in capacity without recording a failure."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))

    node = (await session.execute(select(Node).where(Node.id == "node-0"))).scalar_one()
    assert node.cpu_cores == 64
    assert node.cluster_id == "cluster-a"
    assert await _count(session, FailureRecord) == 0


async def test_cluster_placeholder_is_named_after_its_id(session) -> None:
    """A placeholder cluster takes its id as its name."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))

    cluster = (await session.execute(select(Cluster).where(Cluster.id == "cluster-a"))).scalar_one()
    assert cluster.name == "cluster-a"



def simulation_run(number=1):
    return SimulationRun(
        run_id=UUID(int=number), cluster_id="cluster-a",
        started_at=datetime(2026, 10, 3, 8, tzinfo=UTC) + timedelta(minutes=number),
    )


def run_message(topic, number=1, *, payload=None, event_type=None):
    run = simulation_run(number)
    if topic is Topic.NODE_EVENTS:
        payload = payload if payload is not None else sample_node()
        message_type, default_type = NodeEventMessage, "node.state"
    elif topic is Topic.GPU_METRICS:
        payload = payload if payload is not None else sample_gpu()
        message_type, default_type = GpuMetricMessage, "gpu.metric"
    elif topic is Topic.JOB_EVENTS:
        payload = payload if payload is not None else sample_job().model_copy(update={"id": f"job-run-{number}"})
        message_type, default_type = JobEventMessage, "job.running"
    else:
        payload = payload if payload is not None else SchedulerEvent(
            id=f"scheduler-run-{number}", type=SchedulerEventType.PLACEMENT,
            job_id=f"job-run-{number}", node_id="node-0", reason="placed",
        )
        message_type, default_type = SchedulerEventMessage, "scheduler.placement"
    return message_type(
        event_type=event_type or default_type, payload=payload, schema_version=2,
        simulation_run=run, timestamp=run.started_at + timedelta(seconds=1),
    )


async def persisted_rows(session):
    return {
        table.__tablename__: sorted(
            [tuple(row) for row in (await session.execute(table.__table__.select())).all()], key=repr,
        )
        for table in (Cluster, Node, Gpu, Job, JobNodeAssignment, FailureRecord, SchedulerEventRecord)
    }


async def seed_previous_run(session, node_health=NodeHealthState.NOT_READY, gpu_health=GpuHealthState.FAILED):
    await apply_event(session, Topic.NODE_EVENTS, run_message(
        Topic.NODE_EVENTS, payload=sample_node(node_health), event_type="node.kubelet_down",
    ))
    gpu = sample_gpu().model_copy(update={"health_state": gpu_health, "temperature_celsius": 92.0})
    await apply_event(session, Topic.GPU_METRICS, run_message(
        Topic.GPU_METRICS, payload=gpu, event_type="gpu.driver_crash",
    ))
    for state, identifier, event_type in [
        (JobState.RUNNING, "old-running", "job.straggler"),
        (JobState.PENDING, "old-pending", "job.pending"),
        (JobState.COMPLETED, "old-completed", "job.completed"),
        (JobState.FAILED, "old-failed", "job.oom_kill"),
    ]:
        job = sample_job(state).model_copy(update={"id": identifier, "failure_reason": "original reason"})
        await apply_event(session, Topic.JOB_EVENTS, run_message(
            Topic.JOB_EVENTS, payload=job, event_type=event_type,
        ))


@pytest.mark.parametrize("first_topic", list(Topic))
async def test_first_event_from_any_topic_reconciles_health_jobs_and_incidents(session, first_topic):
    await seed_previous_run(session)
    before = await persisted_rows(session)
    terminal_before = await session.execute(Job.__table__.select().where(Job.id.in_(["old-completed", "old-failed"])))
    terminal_before = sorted([tuple(row) for row in terminal_before], key=repr)
    disposition = await apply_event(session, first_topic, run_message(first_topic, 2))
    assert disposition.value == "applied"
    session.expire_all()
    assert (await session.get(Node, "node-0")).health_state == "READY"
    assert (await session.get(Gpu, "gpu-0-0")).health_state == "HEALTHY"
    for identifier in ["old-running", "old-pending"]:
        job = await session.get(Job, identifier)
        assert (job.lifecycle_state, job.failure_reason) == ("FAILED", "simulation reset")
        assert job.completed_at == job.updated_at == simulation_run(2).started_at
    terminal_after = await session.execute(Job.__table__.select().where(Job.id.in_(["old-completed", "old-failed"])))
    assert sorted([tuple(row) for row in terminal_after], key=repr) == terminal_before
    incidents = (await session.scalars(select(FailureRecord))).all()
    assert len(incidents) == len(before["failure_records"])
    assert all(incident.resolved_at == simulation_run(2).started_at for incident in incidents)
    assert await _count(session, JobNodeAssignment) >= len(before["job_node_assignments"])
    assert {incident.event_id for incident in incidents} == {row[1] for row in before["failure_records"]}
    cluster = await session.get(Cluster, "cluster-a")
    assert cluster.simulation_run_id == str(simulation_run(2).run_id)
    assert cluster.simulation_run_started_at == simulation_run(2).started_at


@pytest.mark.parametrize("node_health,gpu_health", [
    (NodeHealthState.DRAINING, GpuHealthState.DEGRADED),
    (NodeHealthState.CORDONED, GpuHealthState.THROTTLING),
])
async def test_boundary_resets_each_unhealthy_entity_state(session, node_health, gpu_health):
    await seed_previous_run(session, node_health, gpu_health)
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    session.expire_all()
    assert (await session.get(Node, "node-0")).health_state == "READY"
    assert (await session.get(Gpu, "gpu-0-0")).health_state == "HEALTHY"


async def test_repeated_reconciliation_and_backend_restart_preserve_current_run(session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from videre.backend.persistence.event_mapping import reconcile_run

    await seed_previous_run(session)
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    await apply_event(session, Topic.NODE_EVENTS, run_message(
        Topic.NODE_EVENTS, 2, payload=sample_node(NodeHealthState.NOT_READY), event_type="node.disk_pressure",
    ))
    before = await persisted_rows(session)
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    async with factory() as restarted_session, restarted_session.begin():
        assert (await reconcile_run(restarted_session, simulation_run(2))).value == "applied"
        assert (await reconcile_run(restarted_session, simulation_run(2))).value == "applied"
    assert await persisted_rows(session) == before


@pytest.mark.parametrize("topic,event_type,payload_factory", [
    (Topic.JOB_EVENTS, "job.running", lambda: sample_job().model_copy(update={"id": "old-running"})),
    (Topic.JOB_EVENTS, "job.pending", lambda: sample_job(JobState.PENDING).model_copy(update={"id": "never-seen"})),
    (Topic.NODE_EVENTS, "node.recovered", sample_node),
    (Topic.NODE_EVENTS, "node.kubelet_down", lambda: sample_node(NodeHealthState.NOT_READY)),
    (Topic.NODE_EVENTS, "node.state", sample_node),
    (Topic.GPU_METRICS, "gpu.recovered", sample_gpu),
    (Topic.GPU_METRICS, "gpu.driver_crash",
     lambda: sample_gpu().model_copy(update={"health_state": GpuHealthState.FAILED})),
    (Topic.GPU_METRICS, "gpu.metric", sample_gpu),
    (Topic.SCHEDULER_EVENTS, "capacity.fragmentation", lambda: SchedulerEvent(
        id="never-seen-scheduler", type=SchedulerEventType.QUEUEING_DELAY, job_id="never-seen",
        node_id="never-seen-node", delay_seconds=1, reason="old placement",
    )),
])
async def test_old_cross_topic_events_cannot_change_new_run(session, topic, event_type, payload_factory):
    await seed_previous_run(session)
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    await apply_event(session, Topic.NODE_EVENTS, run_message(
        Topic.NODE_EVENTS, 2, payload=sample_node(NodeHealthState.NOT_READY), event_type="node.kubelet_down",
    ))
    await apply_event(session, Topic.GPU_METRICS, run_message(
        Topic.GPU_METRICS, 2, payload=sample_gpu().model_copy(update={"health_state": GpuHealthState.FAILED}),
        event_type="gpu.driver_crash",
    ))
    before = await persisted_rows(session)
    assert (await apply_event(session, topic, run_message(
        topic, 1, payload=payload_factory(), event_type=event_type,
    ))).value == "stale_run"
    assert await persisted_rows(session) == before


async def test_previously_unseen_old_runs_cannot_regress_the_boundary(session):
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    await apply_event(session, Topic.GPU_METRICS, run_message(Topic.GPU_METRICS, 3))
    before = await persisted_rows(session)
    for number in [1, 2]:
        assert (await apply_event(session, Topic.SCHEDULER_EVENTS, run_message(
            Topic.SCHEDULER_EVENTS, number,
        ))).value == "stale_run"
    assert await persisted_rows(session) == before


@pytest.mark.parametrize("topic", list(Topic))
async def test_legacy_events_are_accepted_until_first_boundary_then_rejected(session, topic):
    legacy = run_message(topic).model_dump()
    legacy.update(schema_version=1, simulation_run=None)
    message = type(run_message(topic)).model_validate(legacy)
    assert (await apply_event(session, topic, message)).value == "applied"
    await apply_event(session, Topic.NODE_EVENTS, run_message(Topic.NODE_EVENTS, 2))
    before = await persisted_rows(session)
    assert (await apply_event(session, topic, message)).value == "legacy_after_boundary"
    assert await persisted_rows(session) == before


@pytest.mark.parametrize("first_topic", [Topic.GPU_METRICS, Topic.SCHEDULER_EVENTS])
async def test_legacy_unknown_placeholders_are_adopted_on_first_boundary(session, first_topic):
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type="gpu.driver_crash",
        payload=sample_gpu().model_copy(update={"health_state": GpuHealthState.FAILED}),
    ))
    await apply_event(session, Topic.SCHEDULER_EVENTS, SchedulerEventMessage(
        event_type="capacity.fragmentation", payload=SchedulerEvent(
            id="old-placeholder", type=SchedulerEventType.QUEUEING_DELAY,
            job_id="old-placeholder-job", node_id="node-0", delay_seconds=1, reason="waiting",
        ),
    ))
    await apply_event(session, first_topic, run_message(first_topic, 2))
    session.expire_all()
    assert (await session.get(Node, "node-0")).cluster_id == "cluster-a"
    job = await session.get(Job, "old-placeholder-job")
    assert (job.cluster_id, job.lifecycle_state, job.failure_reason) == ("cluster-a", "FAILED", "simulation reset")
    assert all(row.resolved_at is not None for row in (await session.scalars(select(FailureRecord))).all())


async def test_reconciliation_does_not_change_another_explicit_cluster(session):
    other = sample_node(NodeHealthState.NOT_READY).model_copy(update={"id": "other-node", "cluster_id": "other"})
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(event_type="node.kubelet_down", payload=other))
    other_job = sample_job().model_copy(update={
        "id": "other-job", "cluster_id": "other", "assigned_node_ids": ["other-node"],
    })
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(event_type="job.running", payload=other_job))
    await apply_event(session, Topic.NODE_EVENTS, run_message(Topic.NODE_EVENTS, 2))
    session.expire_all()
    assert (await session.get(Node, "other-node")).health_state == "NOT_READY"
    assert (await session.get(Job, "other-job")).lifecycle_state == "RUNNING"
    failure = await session.scalar(select(FailureRecord).where(FailureRecord.entity_id == "other-node"))
    assert failure.resolved_at is None


@pytest.mark.parametrize("conflict", ["equal_time_different_id", "same_id_different_time"])
async def test_inconsistent_run_metadata_is_rejected_without_writes(session, conflict):
    await apply_event(session, Topic.NODE_EVENTS, run_message(Topic.NODE_EVENTS, 2))
    run = simulation_run(2)
    run = run.model_copy(update=(
        {"run_id": UUID(int=99)} if conflict == "equal_time_different_id"
        else {"started_at": run.started_at + timedelta(minutes=1)}
    ))
    message = run_message(Topic.NODE_EVENTS, 2).model_copy(update={"simulation_run": run})
    before = await persisted_rows(session)
    assert (await apply_event(session, Topic.NODE_EVENTS, message)).value == "conflicting_run"
    assert await persisted_rows(session) == before


@pytest.mark.parametrize("failure_phase", ["after_reset", "after_event"])
async def test_boundary_and_reset_roll_back_with_triggering_event_failure(session, failure_phase):
    from sqlalchemy.exc import DBAPIError

    from videre.backend.persistence.event_mapping import reconcile_run

    await seed_previous_run(session)
    before = await persisted_rows(session)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            if failure_phase == "after_reset":
                await reconcile_run(session, simulation_run(2))
            else:
                await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
            await session.execute(text("SELECT 1 / 0"))
    assert await persisted_rows(session) == before
    assert (await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))).value == "applied"


async def test_superseded_history_follows_existing_retention_policy(session):
    await seed_previous_run(session)
    await apply_event(session, Topic.NODE_EVENTS, run_message(Topic.NODE_EVENTS, 2))
    assert await _count(session, FailureRecord) == 4
    assert await _count(session, Job) == 4
    cutoff = simulation_run(2).started_at + timedelta(days=3)
    deleted = await prune_once(session, cutoff=cutoff)
    assert deleted["failure_records"] == 4
    assert deleted["jobs"] == 4
    assert await _count(session, Node) == 1
    assert await _count(session, Gpu) == 1
