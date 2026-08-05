from datetime import UTC, datetime

import pytest_asyncio
from httpx2 import ASGITransport, AsyncClient

from test_cache import FakeRedis
from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.application import create_application
from videre.backend.cache.snapshot import ClusterHealthSnapshot
from videre.backend.cache.store import write_snapshot
from videre.backend.dependencies import get_redis, get_session
from videre.backend.persistence.event_mapping import apply_event
from videre.backend.routes.pagination import MAXIMUM_PAGE_SIZE
from videre.backend.settings import Settings
from videre.event_types import EventType, LifecycleEventType
from videre.events import GpuMetricMessage, JobEventMessage, NodeEventMessage, Topic
from videre.models import JobState, NodeHealthState


async def seed(session) -> None:
    for node_id, health_state in (
        ("node-0", NodeHealthState.READY),
        ("node-1", NodeHealthState.DRAINING),
    ):
        node = sample_node(health_state)
        node.id = node_id
        await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
            event_type=LifecycleEventType.NODE_STATE.value, payload=node
        ))

    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=sample_gpu()
    ))
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=sample_job(JobState.RUNNING)
    ))

    failed = sample_job(JobState.FAILED)
    failed.id = "job-2"
    failed.failure_reason = "OOMKilled"
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_OOM_KILL.value, payload=failed
    ))
    await session.flush()


@pytest_asyncio.fixture
async def client(session):
    application = create_application(Settings())
    redis_client = FakeRedis()
    application.dependency_overrides[get_session] = lambda: session
    application.dependency_overrides[get_redis] = lambda: redis_client
    application.state.fake_redis = redis_client
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        async_client.app = application
        yield async_client


async def test_clusters_returns_cached_snapshots(session, client) -> None:
    """The clusters endpoint serves whatever the Redis snapshot cache holds."""

    await seed(session)
    await write_snapshot(
        client.app.state.fake_redis,
        ClusterHealthSnapshot(cluster_id="cluster-a", cluster_name="cluster-a"),
        ttl_seconds=20,
    )

    response = await client.get("/clusters")
    assert response.status_code == 200
    assert [item["cluster_id"] for item in response.json()] == ["cluster-a"]


async def test_clusters_returns_503_when_the_cache_is_empty(client) -> None:
    """An empty cache returns 503 rather than silently degrading into an aggregation query."""

    assert (await client.get("/clusters")).status_code == 503


async def test_single_cluster_404s_when_not_cached(client) -> None:
    """Requesting a cluster that is not cached returns 404."""

    assert (await client.get("/clusters/missing")).status_code == 404


async def test_list_nodes_paginates(session, client) -> None:
    """The node list honours the requested page size and reports the unpaged total."""

    await seed(session)
    response = await client.get("/nodes", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2
    assert body["limit"] == 1


async def test_list_nodes_filters_by_health_state(session, client) -> None:
    """The node list filters by health state on the server."""

    await seed(session)
    body = (await client.get("/nodes", params={"health_state": NodeHealthState.DRAINING.value})).json()
    assert [item["id"] for item in body["items"]] == ["node-1"]


async def test_node_detail_includes_its_gpus(session, client) -> None:
    """Node detail nests its GPUs, which is how the GPU drill-down obtains its data."""

    await seed(session)
    body = (await client.get("/nodes/node-0")).json()
    assert body["id"] == "node-0"
    assert [gpu["id"] for gpu in body["gpus"]] == ["gpu-0-0"]


async def test_node_detail_404s_for_an_unknown_id(client) -> None:
    """An unknown node id returns 404."""

    assert (await client.get("/nodes/does-not-exist")).status_code == 404


async def test_page_size_above_the_maximum_is_rejected(client) -> None:
    """A page size beyond the maximum is rejected, bounding response size."""

    assert (await client.get("/nodes", params={"limit": MAXIMUM_PAGE_SIZE + 1})).status_code == 422


async def test_list_jobs_filters_by_lifecycle_state(session, client) -> None:
    """The job list filters by lifecycle state and carries the failure reason."""

    await seed(session)
    body = (await client.get("/jobs", params={"lifecycle_state": JobState.FAILED.value})).json()
    assert [item["id"] for item in body["items"]] == ["job-2"]
    assert body["items"][0]["failure_reason"] is not None


async def test_job_detail_flattens_node_assignments(session, client) -> None:
    """Job detail flattens the join table into a list of assigned node ids."""

    await seed(session)
    body = (await client.get("/jobs/job-1")).json()
    assert body["assigned_node_ids"] == ["node-0"]


async def test_job_detail_404s_for_an_unknown_id(client) -> None:
    """An unknown job id returns 404."""

    assert (await client.get("/jobs/does-not-exist")).status_code == 404


async def test_failures_filters_unresolved_only(session, client) -> None:
    """The failures endpoint separates resolved records from unresolved ones."""

    await seed(session)
    node = sample_node(NodeHealthState.NOT_READY)
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value, payload=node
    ))
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_RECOVERED.value, payload=sample_node()
    ))
    await session.flush()

    unresolved = (await client.get("/failures", params={"resolved": "false"})).json()
    resolved = (await client.get("/failures", params={"resolved": "true"})).json()

    assert all(item["resolved_at"] is None for item in unresolved["items"])
    assert all(item["resolved_at"] is not None for item in resolved["items"])
    assert resolved["total"] >= 1


async def test_failures_filters_by_entity(session, client) -> None:
    """The failures endpoint narrows to a single entity."""

    await seed(session)
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_DISK_PRESSURE.value,
        payload=sample_node(NodeHealthState.NOT_READY),
    ))
    await session.flush()

    body = (await client.get("/failures", params={"entity_type": "node", "entity_id": "node-0"})).json()
    assert body["total"] >= 1
    assert all(item["entity_id"] == "node-0" for item in body["items"])


async def test_failures_since_excludes_older_records(session, client) -> None:
    """A since bound excludes records detected before it."""

    await seed(session)
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_CNI_FAILURE.value,
        timestamp=datetime(2020, 1, 1, tzinfo=UTC),
        payload=sample_node(NodeHealthState.NOT_READY),
    ))
    await session.flush()

    body = (await client.get("/failures", params={"since": "2024-01-01T00:00:00Z"})).json()
    assert all(item["detected_at"] >= "2024-01-01" for item in body["items"])


async def test_capacity_counts_drained_nodes_and_unavailable_gpus(session, client) -> None:
    """Capacity counts drained nodes and the GPUs stranded on unhealthy ones."""

    await seed(session)
    draining_gpu = sample_gpu()
    draining_gpu.id = "gpu-1-0"
    draining_gpu.node_id = "node-1"
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=draining_gpu
    ))
    await session.flush()

    body = (await client.get("/capacity")).json()
    summary = next(item for item in body if item["cluster_id"] == "cluster-a")
    assert summary["drained_node_count"] == 1
    assert summary["unavailable_gpus"] == 1
    assert summary["total_gpus"] == 2


async def test_capacity_counts_idle_gpus_only_on_nodes_without_running_jobs(session, client) -> None:
    """Only GPUs on nodes running no job count as reserved-but-idle capacity."""

    await seed(session)
    idle_gpu = sample_gpu()
    idle_gpu.id = "gpu-1-0"
    idle_gpu.node_id = "node-1"
    idle_gpu.utilization_percentage = 0.0
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=idle_gpu
    ))
    ready_node = sample_node(NodeHealthState.READY)
    ready_node.id = "node-1"
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=ready_node
    ))
    await session.flush()

    body = (await client.get("/capacity")).json()
    summary = next(item for item in body if item["cluster_id"] == "cluster-a")
    assert summary["idle_reserved_gpus"] == 1
