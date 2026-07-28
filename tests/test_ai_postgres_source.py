from datetime import UTC, datetime

from test_ai_fingerprint import fail_gpu, seed
from test_event_mapping import sample_gpu, sample_node
from videre.backend.ai.postgres_source import load_postgres_context
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import FailureEntityTable
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


# --- Missing entities ---


async def test_missing_node_returns_none(session) -> None:
    assert await load_postgres_context(session, FailureEntityTable.NODE, "node-absent") is None


async def test_missing_gpu_returns_none(session) -> None:
    assert await load_postgres_context(session, FailureEntityTable.GPU, "gpu-absent") is None


async def test_missing_job_returns_none(session) -> None:
    assert await load_postgres_context(session, FailureEntityTable.JOB, "job-absent") is None


# --- Entity state ---


async def test_node_context_includes_its_gpus(session) -> None:
    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert context.node is not None and context.node.id == "node-0"
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]


async def test_gpu_context_includes_its_parent_node(session) -> None:
    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert context.node is not None and context.node.id == "node-0"
    assert [gpu.id for gpu in context.gpus] == ["gpu-0-0"]


async def test_job_context_includes_assigned_nodes(session) -> None:
    await seed(session)
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert context.job is not None and context.job.id == "job-1"
    assert context.job.assigned_node_ids == ["node-0"]


# --- Failure history ---


async def test_node_context_carries_its_gpus_failures(session) -> None:
    await seed(session)
    failure_id = await fail_gpu(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert [failure.id for failure in context.unresolved_failures] == [failure_id]


async def test_gpu_context_carries_its_own_failure(session) -> None:
    await seed(session)
    failure_id = await fail_gpu(session)
    context = await load_postgres_context(session, FailureEntityTable.GPU, "gpu-0-0")
    assert context is not None
    assert [failure.id for failure in context.unresolved_failures] == [failure_id]


async def test_job_context_carries_its_nodes_failures(session) -> None:
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


# --- Scheduler events ---


async def test_node_context_includes_scheduler_events(session) -> None:
    await seed(session)
    await add_queueing_delay(session)
    context = await load_postgres_context(session, FailureEntityTable.NODE, "node-0")
    assert context is not None
    assert [event.delay_seconds for event in context.scheduler_events] == [42.0]


async def test_job_context_includes_scheduler_events(session) -> None:
    await seed(session)
    await add_queueing_delay(session)
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert context is not None
    assert [event.related_job_id for event in context.scheduler_events] == ["job-1"]
