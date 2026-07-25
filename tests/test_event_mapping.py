from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

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
    Topic,
)
from videre.models import (
    GPU,
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


# --- Completeness ---


def test_every_failure_event_type_has_a_category() -> None:
    assert set(FAILURE_CATEGORIES) == set(EventType)


# --- Per-topic persistence ---


async def test_node_event_upserts_the_node_and_records_a_failure(session) -> None:
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
    gpu = sample_gpu()
    gpu.utilization_percentage = 87.5
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(event_type="gpu.metric", payload=gpu))

    stored = (await session.execute(select(Gpu).where(Gpu.id == "gpu-0-0"))).scalar_one()
    assert stored.utilization_percentage == 87.5
    assert await _count(session, FailureRecord) == 0


async def test_job_event_writes_the_job_and_its_node_assignments(session) -> None:
    message = JobEventMessage(event_type="job.running", payload=sample_job())
    await apply_event(session, Topic.JOB_EVENTS, message)

    job = (await session.execute(select(Job).where(Job.id == "job-1"))).scalar_one()
    assert job.lifecycle_state == JobState.RUNNING.value
    assert job.requested_gpu_count == 1

    assignment = (await session.execute(select(JobNodeAssignment))).scalar_one()
    assert (assignment.job_id, assignment.node_id) == ("job-1", "node-0")


async def test_failed_job_gets_a_completed_at_so_retention_can_reach_it(session) -> None:
    failed = sample_job(JobState.FAILED)
    assert failed.finished_at is None
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_OOM_KILL.value, payload=failed
    ))

    job = (await session.execute(select(Job).where(Job.id == "job-1"))).scalar_one()
    assert job.completed_at is not None


async def test_scheduler_event_is_persisted(session) -> None:
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


# --- Idempotency, ordering, resolution ---


async def test_reprocessing_the_same_message_creates_one_failure_record(session) -> None:
    message = NodeEventMessage(
        event_type=EventType.NODE_DISK_PRESSURE.value, payload=sample_node(NodeHealthState.NOT_READY)
    )
    await apply_event(session, Topic.NODE_EVENTS, message)
    await apply_event(session, Topic.NODE_EVENTS, message)

    assert await _count(session, FailureRecord) == 1
    assert await _count(session, Node) == 1


async def test_gpu_arriving_before_its_node_creates_a_placeholder(session) -> None:
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


# --- Retention ---


async def test_pruning_removes_aged_history_but_keeps_current_state_and_open_failures(session) -> None:
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


async def test_reprocessing_a_scheduler_event_is_a_no_op(session) -> None:
    # a redelivered scheduler event collides on its primary key as well as on event_id
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
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))

    node = (await session.execute(select(Node).where(Node.id == "node-0"))).scalar_one()
    assert node.cpu_cores == 64                     # real capacity, not a placeholder
    assert node.cluster_id == "cluster-a"
    assert await _count(session, FailureRecord) == 0    # routine state is not a failure


async def test_cluster_placeholder_is_named_after_its_id(session) -> None:
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))

    cluster = (await session.execute(select(Cluster).where(Cluster.id == "cluster-a"))).scalar_one()
    assert cluster.name == "cluster-a"    # no event carries a display name; never show "(pending)"
