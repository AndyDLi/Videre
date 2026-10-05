
import pytest
from sqlalchemy import delete, select, update

from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.ai.fingerprint import load_fingerprint
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import FailureEntityTable, FailureRecord, Gpu, Job, JobNodeAssignment, Node
from videre.event_types import EventType, LifecycleEventType
from videre.events import GpuMetricMessage, JobEventMessage, NodeEventMessage, Topic
from videre.models import GpuHealthState, JobState, NodeHealthState


async def seed(session, node_health=NodeHealthState.READY, job_state=JobState.RUNNING) -> None:
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node(node_health)
    ))
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=sample_gpu()
    ))
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=sample_job(job_state)
    ))
    await session.flush()


async def fail_gpu(session, event_type: EventType = EventType.GPU_THERMAL_THROTTLING) -> str:
    gpu = sample_gpu()
    gpu.health_state = GpuHealthState.THROTTLING
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(event_type=event_type.value, payload=gpu))
    await session.flush()
    return str((await session.execute(
        select(FailureRecord.id).where(FailureRecord.entity_id == gpu.id, FailureRecord.resolved_at.is_(None))
    )).scalars().one())


async def test_missing_node_returns_none(session) -> None:
    """An unknown node has no fingerprint, which is how the endpoint detects a 404."""

    assert await load_fingerprint(session, FailureEntityTable.NODE, "node-absent") is None


async def test_missing_gpu_returns_none(session) -> None:
    """An unknown GPU has no fingerprint."""

    assert await load_fingerprint(session, FailureEntityTable.GPU, "gpu-absent") is None


async def test_missing_job_returns_none(session) -> None:
    """An unknown job has no fingerprint."""

    assert await load_fingerprint(session, FailureEntityTable.JOB, "job-absent") is None


async def test_node_fingerprint_reports_health_state(session) -> None:
    """A node's fingerprint carries its health state and an empty failure set when healthy."""

    await seed(session, node_health=NodeHealthState.DRAINING)
    fingerprint = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    assert fingerprint is not None
    assert fingerprint.health_state == NodeHealthState.DRAINING.value
    assert fingerprint.unresolved_failure_ids == ()


async def test_gpu_fingerprint_reports_health_state(session) -> None:
    """A GPU's fingerprint carries its health state."""

    await seed(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    assert fingerprint is not None
    assert fingerprint.health_state == GpuHealthState.HEALTHY.value


async def test_job_fingerprint_reports_lifecycle_state(session) -> None:
    """A job's fingerprint uses its lifecycle state in place of a health state."""

    await seed(session, job_state=JobState.RUNNING)
    fingerprint = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert fingerprint is not None
    assert fingerprint.health_state == JobState.RUNNING.value


async def test_unresolved_failure_ids_are_listed(session) -> None:
    """An entity's open failures appear in its fingerprint."""

    await seed(session)
    failure_id = await fail_gpu(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    assert fingerprint is not None
    assert fingerprint.unresolved_failure_ids == (failure_id,)


async def test_resolved_failures_are_excluded(session) -> None:
    """Once a failure resolves it drops out of the fingerprint's failure set."""

    await seed(session)
    await fail_gpu(session)
    recovered = sample_gpu()
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_RECOVERED.value, payload=recovered
    ))
    await session.flush()

    fingerprint = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    assert fingerprint is not None
    assert fingerprint.unresolved_failure_ids == ()


async def test_node_fingerprint_includes_its_gpu_failure(session) -> None:
    """A node diagnosis changes when its own GPU fails."""

    await seed(session)
    failure_id = await fail_gpu(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    assert fingerprint is not None
    assert fingerprint.unresolved_failure_ids == (failure_id,)


async def test_fingerprint_changes_when_health_state_changes(session) -> None:
    """A health-state change produces a new cache key, so a stale analysis is not reused."""

    await seed(session)
    before = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value, payload=sample_node(NodeHealthState.NOT_READY)
    ))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")

    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_fingerprint_changes_when_the_failure_set_changes(session) -> None:
    """A newly raised failure produces a new cache key."""

    await seed(session)
    before = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    await fail_gpu(session, EventType.GPU_XID_ERROR)
    after = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")

    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_fingerprint_is_stable_across_metric_churn(session) -> None:
    """Fluctuating utilization and temperature leave the cache key unchanged, so the cache still hits."""

    await seed(session)
    before = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")

    churned = sample_gpu()
    churned.utilization_percentage = 91.4
    churned.temperature_celsius = 78.2
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=churned
    ))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")

    assert before is not None and after is not None
    assert before.cache_fingerprint == after.cache_fingerprint


@pytest.mark.parametrize("entity_type,entity_id,table,row_id,column,value", [
    (FailureEntityTable.JOB, "job-1", Gpu, "gpu-0-0", "health_state", "FAILED"),
    (FailureEntityTable.NODE, "node-0", Gpu, "gpu-0-0", "health_state", "FAILED"),
    (FailureEntityTable.GPU, "gpu-0-0", Node, "node-0", "health_state", "NOT_READY"),
    (FailureEntityTable.JOB, "job-1", Node, "node-0", "health_state", "NOT_READY"),
    (FailureEntityTable.JOB, "job-1", Job, "job-1", "failure_reason", "timeout waiting for NCCL"),
])
async def test_related_diagnostic_state_changes_the_key(session, entity_type, entity_id, table, row_id, column, value):
    await seed(session)
    before = await load_fingerprint(session, entity_type, entity_id)
    await session.execute(update(table).where(table.id == row_id).values({column: value}))
    after = await load_fingerprint(session, entity_type, entity_id)
    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_assignment_changes_key_even_when_nodes_are_healthy(session):
    from test_ai_postgres_source import add_node
    await seed(session)
    await add_node(session, "node-other")
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    await session.execute(delete(JobNodeAssignment).where(JobNodeAssignment.job_id == "job-1"))
    session.add(JobNodeAssignment(job_id="job-1", node_id="node-other"))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_related_incident_creation_resolution_and_correlation_changes_invalidate(session):
    from datetime import UTC, datetime

    from test_ai_postgres_source import add_node, failure
    await seed(session)
    await add_node(session, "node-other")
    session.add(failure("direct"))
    await session.flush()
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    session.add(failure("related", "node", "node-other"))
    await session.flush()
    created = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    await session.execute(
        update(FailureRecord).where(FailureRecord.id == "related").values(resolved_at=datetime.now(UTC))
    )
    resolved = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    await session.execute(
        update(FailureRecord).where(FailureRecord.id == "related").values(correlation_id="other-incident")
    )
    disconnected = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert all(value is not None for value in (before, created, resolved, disconnected))
    assert before.cache_fingerprint != created.cache_fingerprint
    assert created.cache_fingerprint != resolved.cache_fingerprint
    assert resolved.cache_fingerprint != disconnected.cache_fingerprint
    assert before.cache_fingerprint == disconnected.cache_fingerprint


async def test_unrelated_node_changes_preserve_key(session):
    from test_ai_postgres_source import add_node, failure
    await seed(session)
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    await add_node(session, "node-unrelated")
    session.add(failure("unrelated", "node", "node-unrelated"))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert before is not None and after is not None
    assert before.cache_fingerprint == after.cache_fingerprint


async def test_recent_evidence_expiring_changes_the_key(session):
    from datetime import UTC, datetime, timedelta

    from test_ai_postgres_source import failure
    await seed(session)
    session.add(failure("recent", resolved_at=datetime.now(UTC)-timedelta(minutes=30)))
    await session.flush()
    before = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    await session.execute(update(FailureRecord).values(resolved_at=datetime.now(UTC)-timedelta(hours=2)))
    after = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_fingerprint_is_independent_of_collection_order(session, monkeypatch):
    from test_ai_postgres_source import add_gpu, failure
    from videre.backend.ai import fingerprint as module
    from videre.backend.ai.postgres_source import load_postgres_context
    await seed(session)
    await add_gpu(session, "gpu-another", "node-0")
    session.add_all([failure("a"), failure("b")])
    await session.flush()
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    async def lookup(*args):
        return context
    monkeypatch.setattr(module, "load_postgres_context", lookup)
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    context.gpus.reverse()
    context.assigned_nodes.reverse()
    context.unresolved_failures.reverse()
    after = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert before is not None and after is not None
    assert before.cache_fingerprint == after.cache_fingerprint
