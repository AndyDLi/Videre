import json

from test_cache import FakeRedis
from videre.backend.cache.snapshot import ClusterHealthSnapshot
from videre.backend.cache.store import write_snapshot
from videre.backend.websocket.limits import (
    MAXIMUM_CONNECTIONS_PER_IP,
    connection_key,
    release,
    try_acquire,
)
from videre.backend.websocket.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, working: bool = True) -> None:
        self.working = working
        self.sent: list[str] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        if not self.working:
            raise ConnectionError("client gone")
        self.sent.append(payload)


class CountingRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def decr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) - 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        await super().set(key, value, ex)
        if key in self.counters:
            self.counters[key] = int(value)


# --- Connection manager ---


async def test_broadcast_reaches_every_connected_client() -> None:
    manager = ConnectionManager()
    first, second = FakeWebSocket(), FakeWebSocket()
    await manager.connect(first)
    await manager.connect(second)

    delivered = await manager.broadcast('{"hello": true}')

    assert delivered == 2
    assert first.sent == second.sent == ['{"hello": true}']


async def test_a_broken_client_is_dropped_without_blocking_the_others() -> None:
    manager = ConnectionManager()
    healthy, broken = FakeWebSocket(), FakeWebSocket(working=False)
    await manager.connect(healthy)
    await manager.connect(broken)

    delivered = await manager.broadcast("payload")

    assert delivered == 1
    assert manager.connection_count == 1
    assert healthy.sent == ["payload"]


async def test_disconnect_removes_the_connection() -> None:
    manager = ConnectionManager()
    websocket = FakeWebSocket()
    await manager.connect(websocket)
    await manager.disconnect(websocket)
    assert manager.connection_count == 0


# --- Per-IP limiting ---


async def test_connections_are_capped_per_ip() -> None:
    redis_client = CountingRedis()
    granted = [await try_acquire(redis_client, "10.0.0.1") for _ in range(MAXIMUM_CONNECTIONS_PER_IP + 2)]

    assert granted[:MAXIMUM_CONNECTIONS_PER_IP] == [True] * MAXIMUM_CONNECTIONS_PER_IP
    assert granted[MAXIMUM_CONNECTIONS_PER_IP:] == [False, False]


async def test_a_refused_connection_does_not_consume_a_slot() -> None:
    redis_client = CountingRedis()
    for _ in range(MAXIMUM_CONNECTIONS_PER_IP):
        await try_acquire(redis_client, "10.0.0.1")
    await try_acquire(redis_client, "10.0.0.1")

    await release(redis_client, "10.0.0.1")
    assert await try_acquire(redis_client, "10.0.0.1") is True


async def test_separate_ips_have_independent_budgets() -> None:
    redis_client = CountingRedis()
    for _ in range(MAXIMUM_CONNECTIONS_PER_IP):
        await try_acquire(redis_client, "10.0.0.1")
    assert await try_acquire(redis_client, "10.0.0.2") is True


async def test_release_never_drives_the_counter_negative() -> None:
    redis_client = CountingRedis()
    await release(redis_client, "10.0.0.1")
    await release(redis_client, "10.0.0.1")
    assert redis_client.counters[connection_key("10.0.0.1")] >= 0


# --- Payload shape ---


async def test_stream_payload_matches_the_clusters_response_shape() -> None:
    from videre.backend.routes.stream import current_payload

    redis_client = CountingRedis()
    await write_snapshot(
        redis_client,
        ClusterHealthSnapshot(cluster_id="cluster-a", cluster_name="cluster-a"),
        ttl_seconds=20,
    )

    payload = json.loads(await current_payload(redis_client))

    assert isinstance(payload, list)
    assert payload[0]["cluster_id"] == "cluster-a"
    assert "nodes_by_health_state" in payload[0]
