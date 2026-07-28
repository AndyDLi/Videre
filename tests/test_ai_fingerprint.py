
from sqlalchemy import select

from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.ai.fingerprint import load_fingerprint
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import FailureEntityTable, FailureRecord
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


# --- Missing entities ---


async def test_missing_node_returns_none(session) -> None:
    assert await load_fingerprint(session, FailureEntityTable.NODE, "node-absent") is None


async def test_missing_gpu_returns_none(session) -> None:
    assert await load_fingerprint(session, FailureEntityTable.GPU, "gpu-absent") is None


async def test_missing_job_returns_none(session) -> None:
    assert await load_fingerprint(session, FailureEntityTable.JOB, "job-absent") is None


# --- State per entity type ---


async def test_node_fingerprint_reports_health_state(session) -> None:
    await seed(session, node_health=NodeHealthState.DRAINING)
    fingerprint = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    assert fingerprint is not None
    assert fingerprint.health_state == NodeHealthState.DRAINING.value
    assert fingerprint.unresolved_failure_ids == ()


async def test_gpu_fingerprint_reports_health_state(session) -> None:
    await seed(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    assert fingerprint is not None
    assert fingerprint.health_state == GpuHealthState.HEALTHY.value


async def test_job_fingerprint_reports_lifecycle_state(session) -> None:
    await seed(session, job_state=JobState.RUNNING)
    fingerprint = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert fingerprint is not None
    assert fingerprint.health_state == JobState.RUNNING.value


# --- Unresolved failure set ---


async def test_unresolved_failure_ids_are_listed(session) -> None:
    await seed(session)
    failure_id = await fail_gpu(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    assert fingerprint is not None
    assert fingerprint.unresolved_failure_ids == (failure_id,)


async def test_resolved_failures_are_excluded(session) -> None:
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


async def test_another_entitys_failure_does_not_leak_in(session) -> None:
    await seed(session)
    await fail_gpu(session)
    fingerprint = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
    assert fingerprint is not None
    assert fingerprint.unresolved_failure_ids == ()


# --- Cache-key stability ---


async def test_fingerprint_changes_when_health_state_changes(session) -> None:
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
    await seed(session)
    before = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    await fail_gpu(session, EventType.GPU_XID_ERROR)
    after = await load_fingerprint(session, FailureEntityTable.GPU, "gpu-0-0")
    
    assert before is not None and after is not None
    assert before.cache_fingerprint != after.cache_fingerprint


async def test_fingerprint_is_stable_across_metric_churn(session) -> None:
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
