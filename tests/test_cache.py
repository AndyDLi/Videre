from sqlalchemy import select

from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.cache.builder import build_all_snapshots, build_snapshot
from videre.backend.cache.refresh import TTL_MULTIPLIER, refresh_once
from videre.backend.cache.snapshot import ClusterHealthSnapshot, cache_key
from videre.backend.cache.store import read_all_snapshots, read_snapshot, write_snapshot
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import Cluster
from videre.event_types import EventType, LifecycleEventType
from videre.events import GpuMetricMessage, JobEventMessage, NodeEventMessage, Topic
from videre.models import JobState, NodeHealthState


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    async def scan_iter(self, match: str = "*"):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


class SingleSessionFactory:
    def __init__(self, session) -> None:
        self._session = session

    def __call__(self) -> "SingleSessionFactory":
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *arguments) -> None:
        return None


def make_snapshot(cluster_id: str = "cluster-a") -> ClusterHealthSnapshot:
    return ClusterHealthSnapshot(
        cluster_id=cluster_id,
        cluster_name=cluster_id,
        nodes_by_health_state={"READY": 3, "NOT_READY": 1},
        unresolved_failure_count=2,
    )


async def test_snapshot_round_trips_through_the_store() -> None:
    """A snapshot written to Redis reads back with its counts intact."""

    redis_client = FakeRedis()
    await write_snapshot(redis_client, make_snapshot(), ttl_seconds=20)

    restored = await read_snapshot(redis_client, "cluster-a")
    assert restored is not None
    assert restored.nodes_by_health_state == {"READY": 3, "NOT_READY": 1}
    assert restored.unresolved_failure_count == 2


async def test_reading_a_missing_snapshot_returns_none() -> None:
    """Reading a cluster that was never cached yields nothing rather than an empty snapshot."""

    assert await read_snapshot(FakeRedis(), "cluster-a") is None


async def test_read_all_returns_every_cached_cluster() -> None:
    """Reading all snapshots returns one entry per cached cluster."""

    redis_client = FakeRedis()
    await write_snapshot(redis_client, make_snapshot("cluster-a"), ttl_seconds=20)
    await write_snapshot(redis_client, make_snapshot("cluster-b"), ttl_seconds=20)

    cached = await read_all_snapshots(redis_client)
    assert {snapshot.cluster_id for snapshot in cached} == {"cluster-a", "cluster-b"}


async def test_snapshot_counts_reflect_persisted_state(session) -> None:
    """A snapshot built from Postgres reports the node and job counts actually stored."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node(NodeHealthState.READY)
    ))
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=sample_job(JobState.RUNNING)
    ))

    cluster = (await session.execute(select(Cluster).where(Cluster.id == "cluster-a"))).scalar_one()
    snapshot = await build_snapshot(session, cluster)

    assert snapshot.nodes_by_health_state[NodeHealthState.READY.value] == 1
    assert snapshot.jobs_by_lifecycle_state[JobState.RUNNING.value] == 1
    assert snapshot.cluster_name == "cluster-a"


async def test_snapshot_counts_only_unresolved_failures(session) -> None:
    """The unresolved failure count rises with a new failure and falls once the entity recovers."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value,
        payload=sample_node(NodeHealthState.NOT_READY),
    ))
    cluster = (await session.execute(select(Cluster).where(Cluster.id == "cluster-a"))).scalar_one()
    assert (await build_snapshot(session, cluster)).unresolved_failure_count == 1

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_RECOVERED.value, payload=sample_node()
    ))
    assert (await build_snapshot(session, cluster)).unresolved_failure_count == 0


async def test_placeholder_clusters_without_nodes_are_excluded(session) -> None:
    """The placeholder cluster created by an out-of-order event never reaches the cache."""

    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=sample_gpu()
    ))
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))

    snapshots = await build_all_snapshots(session)
    assert {snapshot.cluster_id for snapshot in snapshots} == {"cluster-a"}


async def test_refresh_writes_one_snapshot_per_cluster_with_a_ttl_beyond_the_interval(session) -> None:
    """Each refresh writes one snapshot per cluster with a TTL outliving the interval, so a stall serves stale data."""

    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))
    redis_client = FakeRedis()

    written = await refresh_once(SingleSessionFactory(session), redis_client, interval_seconds=5.0)

    assert written == 1
    ttl = redis_client.expiries[cache_key("cluster-a")]
    assert ttl == int(5.0 * TTL_MULTIPLIER)
    assert ttl > 5

async def test_reset_snapshot_and_cache_preserve_history_and_new_incidents(session):
    from prometheus_client import REGISTRY

    from test_event_mapping import persisted_rows, run_message, seed_previous_run, simulation_run
    from videre.backend.persistence.event_mapping import reconcile_run

    await seed_previous_run(session)
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    cluster = await session.get(Cluster, "cluster-a")
    reset = await build_snapshot(session, cluster)
    assert reset.nodes_by_health_state == {"READY": 1}
    assert reset.gpus_by_health_state == {"HEALTHY": 1}
    assert reset.jobs_by_lifecycle_state == {"FAILED": 3, "COMPLETED": 1, "RUNNING": 1}
    assert reset.unresolved_failure_count == 0
    assert len((await persisted_rows(session))["failure_records"]) == 4
    await apply_event(session, Topic.NODE_EVENTS, run_message(
        Topic.NODE_EVENTS, 2, payload=sample_node(NodeHealthState.NOT_READY), event_type="node.kubelet_down",
    ))
    before = await persisted_rows(session)
    await reconcile_run(session, simulation_run(2))
    assert await persisted_rows(session) == before
    redis_client = FakeRedis()
    await refresh_once(SingleSessionFactory(session), redis_client, interval_seconds=5)
    cached = await read_snapshot(redis_client, "cluster-a")
    assert cached.nodes_by_health_state == {"NOT_READY": 1}
    assert cached.unresolved_failure_count == 1
    assert REGISTRY.get_sample_value("videre_unresolved_failures") == 1
    assert REGISTRY.get_sample_value("videre_jobs_by_state", {"cluster_id": "cluster-a", "state": "PENDING"}) == 0
