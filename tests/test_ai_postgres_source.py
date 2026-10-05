from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from test_ai_fingerprint import fail_gpu, seed
from test_event_mapping import sample_gpu, sample_node
from videre.backend.ai.postgres_source import load_postgres_context
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import FailureEntityTable, FailureRecord, JobNodeAssignment
from videre.event_types import EventType, LifecycleEventType
from videre.events import GpuMetricMessage, NodeEventMessage, SchedulerEventMessage, Topic
from videre.models import SchedulerEvent, SchedulerEventType


async def add_queueing_delay(session) -> None:
    await apply_event(session, Topic.SCHEDULER_EVENTS, SchedulerEventMessage(
        event_type=EventType.CAPACITY_FRAGMENTATION.value,
        payload=SchedulerEvent(
            id="scheduler-1",
            type=SchedulerEventType.QUEUEING_DELAY,
            timestamp=datetime.now(UTC),
            job_id="job-1",
            node_id="node-0",
            delay_seconds=42.0,
            reason="no eligible capacity",
        ),
    ))
    await session.flush()


async def test_missing_node_returns_none(session) -> None:
    """An unknown node yields no context rather than an empty one."""

    assert await load_postgres_context(session, FailureEntityTable.NODE, "node-absent") is None


async def test_missing_gpu_returns_none(session) -> None:
    """An unknown GPU yields no context rather than an empty one."""

    assert await load_postgres_context(session, FailureEntityTable.GPU, "gpu-absent") is None


async def test_missing_job_returns_none(session) -> None:
    """An unknown job yields no context rather than an empty one."""

    assert await load_postgres_context(session, FailureEntityTable.JOB, "job-absent") is None


async def test_node_context_includes_its_gpus(session) -> None:
    """A node's context carries the node itself and every GPU attached to it."""

    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert context.node is not None and context.node.id == "node-0"
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]


async def test_gpu_context_includes_its_parent_node(session) -> None:
    """A GPU's context reaches up to its parent node, since node health explains GPU symptoms."""

    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert context.node is not None and context.node.id == "node-0"
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]


async def test_job_context_includes_assigned_nodes(session) -> None:
    """A job's context resolves the nodes it was placed on."""

    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert context.job is not None and context.job.id == "job-1"
    assert context.job.assigned_node_ids == ["node-0"]


async def test_node_context_carries_its_gpus_failures(session) -> None:
    """A node's context includes failures raised against its GPUs, not only against itself."""

    await seed(session)
    failure_id = await fail_gpu(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert [failure.id for failure in context.unresolved_failures] == [failure_id]


async def test_gpu_context_carries_its_own_failure(session) -> None:
    """A GPU's context includes the unresolved failure raised against it."""

    await seed(session)
    failure_id = await fail_gpu(session)
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert [failure.id for failure in context.unresolved_failures] == [failure_id]


async def test_job_context_carries_its_nodes_failures(session) -> None:
    """A job's context includes failures on the nodes it runs on, which is usually the real cause."""

    await seed(session)
    await apply_event(
        session,
        Topic.NODE_EVENTS,
        NodeEventMessage(
            event_type=EventType.NODE_DISK_PRESSURE.value,
            payload=sample_node()
        )
    )
    await session.flush()

    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert [failure.root_cause_tag for failure in context.unresolved_failures] == [
        EventType.NODE_DISK_PRESSURE.value
    ]


async def test_resolved_failures_land_in_the_history_section(session) -> None:
    """Once an entity recovers, its failure moves from the unresolved list into recent history."""

    await seed(session)
    await fail_gpu(session)

    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_RECOVERED.value, payload=sample_gpu()
    ))
    await session.flush()

    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert context.unresolved_failures == []
    assert len(context.recently_resolved_failures) == 1


async def test_node_context_includes_scheduler_events(session) -> None:
    """A node's context carries the scheduler events recorded against it."""

    await seed(session)
    await add_queueing_delay(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert [event.delay_seconds for event in context.scheduler_events] == [42.0]


async def test_job_context_includes_scheduler_events(session) -> None:
    """A job's context carries the scheduler events recorded against it."""

    await seed(session)
    await add_queueing_delay(session)
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert [event.related_job_id for event in context.scheduler_events] == ["job-1"]


async def add_node(session, node_id: str, cluster_id: str = "cluster-a") -> None:
    node = sample_node()
    node.id, node.cluster_id = node_id, cluster_id
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=node,
    ))
    await session.flush()


async def add_gpu(session, gpu_id: str, node_id: str) -> None:
    gpu = sample_gpu()
    gpu.id, gpu.node_id = gpu_id, node_id
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=gpu,
    ))
    await session.flush()


def failure(failure_id, entity_type="gpu", entity_id="gpu-0-0", correlation="incident-a", resolved_at=None):
    return FailureRecord(
        id=failure_id, event_id=failure_id, entity_type=entity_type, entity_id=entity_id,
        category="node_not_ready" if entity_type == "node" else entity_type,
        root_cause_tag="test_fault", correlation_id=correlation,
        detected_at=datetime(2026, 1, 1, tzinfo=UTC), resolved_at=resolved_at,
    )


async def test_job_includes_assigned_gpu_failures_and_health(session) -> None:
    await seed(session)
    failure_id = await fail_gpu(session)
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert [row.id for row in context.unresolved_failures] == [failure_id]
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]
    assert [(node.id, node.health_state) for node in context.assigned_nodes] == [("node-0", "READY")]


async def test_correlations_are_one_hop_deduplicated_and_cluster_scoped(session) -> None:
    await seed(session)
    await add_node(session, "node-other")
    await add_node(session, "node-foreign", "cluster-b")
    session.add_all([
        failure("direct"), failure("direct-two", "node", "node-0"),
        failure("related", "node", "node-other"),
        failure("foreign", "node", "node-foreign"),
        failure("unrelated", "node", "node-other", "incident-b"),
        failure("dangling", "node", "missing"),
        failure("recent", "node", "node-other", resolved_at=datetime.now(UTC)-timedelta(minutes=30)),
        failure("old", "node", "node-other", resolved_at=datetime.now(UTC)-timedelta(hours=2)),
    ])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert {row.id for row in context.unresolved_failures} == {"direct", "direct-two"}
    assert [row.id for row in context.correlated_failures] == ["related", "recent"]


async def test_empty_correlation_does_not_expand(session) -> None:
    await seed(session)
    await add_node(session, "node-other")
    session.add_all([failure("direct", correlation=""), failure("other", "node", "node-other", "")])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None and context.correlated_failures == []


@pytest.mark.parametrize("extra", [0, 1])
async def test_gpu_and_failure_caps_report_only_overflow(session, extra) -> None:
    await seed(session)
    for index in range(63 + extra):
        await add_gpu(session, f"gpu-extra-{index:02}", "node-0")
    session.add_all([failure(f"failure-{index:02}") for index in range(20 + extra)])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert len(context.gpus) == 64
    assert len(context.unresolved_failures) == 20
    assert [row.id for row in context.unresolved_failures] == [f"failure-{index:02}" for index in range(20)]
    assert ("gpus" in context.truncated_sections) == bool(extra)
    assert ("unresolved_failures" in context.truncated_sections) == bool(extra)


async def test_assignment_cap_excludes_foreign_nodes(session) -> None:
    await seed(session)
    for index in range(8):
        node_id = f"node-extra-{index}"
        await add_node(session, node_id)
        session.add(JobNodeAssignment(job_id="job-1", node_id=node_id))
    await add_node(session, "node-foreign", "cluster-b")
    session.add(JobNodeAssignment(job_id="job-1", node_id="node-foreign"))
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None and context.job is not None
    assert context.job.assigned_node_ids == ["node-0"] + [f"node-extra-{i}" for i in range(7)]
    assert len(context.assigned_nodes) == 8
    assert "assigned_nodes" in context.truncated_sections


async def test_correlated_cap_and_gpu_scope_do_not_expand_siblings(session) -> None:
    await seed(session)
    await add_gpu(session, "gpu-sibling", "node-0")
    session.add(failure("seed"))
    session.add_all([failure(f"correlated-{i:02}", "gpu", "gpu-sibling") for i in range(21)])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]
    assert [row.id for row in context.correlated_failures] == [f"correlated-{i:02}" for i in range(20)]
    assert "correlated_failures" in context.truncated_sections


async def test_unassigned_job_still_includes_its_own_failures(session):
    await seed(session)
    await session.execute(delete(JobNodeAssignment))
    session.add(failure("job-fault", "job", "job-1"))
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None and context.job is not None
    assert context.job.assigned_node_ids == []
    assert context.assigned_nodes == [] and context.gpus == []
    assert [row.id for row in context.unresolved_failures] == ["job-fault"]


async def test_recent_history_and_scheduler_overflow_are_reported(session):
    from videre.database.tables import SchedulerEventRecord
    await seed(session)
    now = datetime.now(UTC)
    session.add_all([failure(f"recent-{i:02}", resolved_at=now) for i in range(21)])
    session.add(failure("old", resolved_at=now-timedelta(hours=2)))
    session.add_all([SchedulerEventRecord(
        id=f"scheduler-{i:02}", event_id=f"scheduler-{i:02}", type="QUEUEING_DELAY", timestamp=now,
        related_job_id="job-1", related_node_id="node-0", delay_seconds=float(i), reason="queued",
    ) for i in range(21)])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert [row.id for row in context.recently_resolved_failures] == [f"recent-{i:02}" for i in range(20)]
    assert [row.delay_seconds for row in context.scheduler_events] == list(range(20))
    assert {"recently_resolved_failures", "scheduler_events"} <= set(context.truncated_sections)


async def test_correlation_seeds_do_not_include_omitted_direct_failures(session):
    await seed(session)
    await add_node(session, "node-other")
    session.add_all([failure(f"direct-{i:02}", correlation=f"incident-{i}") for i in range(21)])
    session.add(failure("outside-seeds", "node", "node-other", "incident-20"))
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert len(context.unresolved_failures) == 20
    assert context.correlated_failures == []


async def test_correlations_filter_gpu_and_job_cluster_membership(session):
    from test_event_mapping import sample_job
    from videre.events import JobEventMessage
    await seed(session)
    for label, cluster in [("same", "cluster-a"), ("foreign", "cluster-b")]:
        await add_node(session, f"node-{label}", cluster)
        await add_gpu(session, f"gpu-{label}", f"node-{label}")
        job = sample_job()
        job.id, job.cluster_id, job.assigned_node_ids = f"job-{label}", cluster, [f"node-{label}"]
        await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
            event_type=LifecycleEventType.JOB_RUNNING.value, payload=job,
        ))
        session.add_all([failure(f"gpu-fault-{label}", "gpu", f"gpu-{label}"),
            failure(f"job-fault-{label}", "job", f"job-{label}")])
    session.add(failure("direct"))
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert {row.id for row in context.correlated_failures} == {"gpu-fault-same", "job-fault-same"}
