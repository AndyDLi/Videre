import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from test_cache import FakeRedis
from videre.backend.cache.snapshot import ClusterHealthSnapshot
from videre.backend.cache.store import write_snapshot
from videre.backend.settings import Settings
from videre.backend.websocket.limits import connection_key, release, try_acquire
from videre.backend.websocket.manager import ConnectionManager

MAXIMUM_CONNECTIONS = 5


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


async def test_broadcast_reaches_every_connected_client() -> None:
    """A broadcast is delivered to every connected client."""

    manager = ConnectionManager()
    first, second = FakeWebSocket(), FakeWebSocket()
    await manager.connect(first)
    await manager.connect(second)

    delivered = await manager.broadcast('{"hello": true}')

    assert delivered == 2
    assert first.sent == second.sent == ['{"hello": true}']


async def test_a_broken_client_is_dropped_without_blocking_the_others() -> None:
    """A client that fails mid-broadcast is dropped while healthy clients still receive the payload."""

    manager = ConnectionManager()
    healthy, broken = FakeWebSocket(), FakeWebSocket(working=False)
    await manager.connect(healthy)
    await manager.connect(broken)

    delivered = await manager.broadcast("payload")

    assert delivered == 1
    assert manager.connection_count == 1
    assert healthy.sent == ["payload"]


async def test_disconnect_removes_the_connection() -> None:
    """Disconnecting removes the client from the broadcast set."""

    manager = ConnectionManager()
    websocket = FakeWebSocket()
    await manager.connect(websocket)
    await manager.disconnect(websocket)
    assert manager.connection_count == 0


async def test_connections_are_capped_per_client() -> None:
    """A client is granted connections up to its cap and refused beyond it."""

    redis_client = CountingRedis()
    granted = [
        await try_acquire(redis_client, "10.0.0.1", MAXIMUM_CONNECTIONS)
        for _ in range(MAXIMUM_CONNECTIONS + 2)
    ]

    assert granted[:MAXIMUM_CONNECTIONS] == [True] * MAXIMUM_CONNECTIONS
    assert granted[MAXIMUM_CONNECTIONS:] == [False, False]


async def test_a_refused_connection_does_not_consume_a_slot() -> None:
    """A refused attempt gives its slot back, so releasing one connection frees capacity."""

    redis_client = CountingRedis()
    for _ in range(MAXIMUM_CONNECTIONS):
        await try_acquire(redis_client, "10.0.0.1", MAXIMUM_CONNECTIONS)
    await try_acquire(redis_client, "10.0.0.1", MAXIMUM_CONNECTIONS)

    await release(redis_client, "10.0.0.1")
    assert await try_acquire(redis_client, "10.0.0.1", MAXIMUM_CONNECTIONS) is True


async def test_separate_clients_have_independent_budgets() -> None:
    """One client exhausting its cap does not block a different address."""

    redis_client = CountingRedis()
    for _ in range(MAXIMUM_CONNECTIONS):
        await try_acquire(redis_client, "10.0.0.1", MAXIMUM_CONNECTIONS)
    assert await try_acquire(redis_client, "10.0.0.2", MAXIMUM_CONNECTIONS) is True


async def test_release_never_drives_the_counter_negative() -> None:
    """Releasing more often than acquiring floors the counter at zero rather than going negative."""

    redis_client = CountingRedis()
    await release(redis_client, "10.0.0.1")
    await release(redis_client, "10.0.0.1")
    assert redis_client.counters[connection_key("10.0.0.1")] >= 0


async def test_a_raised_cap_admits_more_connections() -> None:
    """Raising the cap admits the additional connections a lower cap would have refused."""

    redis_client = CountingRedis()
    granted = [await try_acquire(redis_client, "10.0.0.1", 100) for _ in range(50)]
    assert granted == [True] * 50


async def test_the_cap_defaults_to_one_hundred_and_is_configurable() -> None:
    """The per-client connection cap defaults to 100 and can be overridden by settings."""

    assert Settings().websocket_maximum_connections_per_client == 100
    assert Settings(websocket_maximum_connections_per_client=25).websocket_maximum_connections_per_client == 25


async def test_stream_payload_matches_the_clusters_response_shape() -> None:
    """The streamed payload reuses the /clusters shape, so one client model serves both."""

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


class BlockedWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.finished = asyncio.Event()
        self.send_calls = 0

    async def send_text(self, payload: str) -> None:
        self.send_calls += 1
        self.started.set()
        try:
            await self.resume.wait()
            await super().send_text(payload)
        finally:
            self.finished.set()


async def test_slow_client_is_skipped_until_it_recovers() -> None:
    manager = ConnectionManager(send_timeout_seconds=0.02)
    blocked, healthy = BlockedWebSocket(), FakeWebSocket()
    await manager.connect(blocked)
    await manager.connect(healthy)

    try:
        first = asyncio.create_task(manager.broadcast("first"))
        await asyncio.wait_for(blocked.started.wait(), 0.5)
        await asyncio.sleep(0)
        assert healthy.sent == ["first"]
        assert await asyncio.wait_for(first, 0.5) == 1
        assert manager.connection_count == 2

        assert await manager.broadcast("second") == 1
        assert blocked.send_calls == 1
        assert healthy.sent == ["first", "second"]

        blocked.resume.set()
        await asyncio.wait_for(blocked.finished.wait(), 0.5)
        assert await manager.broadcast("latest") == 2
        assert blocked.sent == ["first", "latest"]
    finally:
        await manager.shutdown()


async def test_initial_send_and_broadcast_share_one_send_per_client() -> None:
    manager = ConnectionManager(send_timeout_seconds=0.02)
    blocked = BlockedWebSocket()
    await manager.connect(blocked)
    try:
        assert await manager.send(blocked, "initial") is False
        assert await manager.broadcast("skipped") == 0
        assert blocked.send_calls == 1
        blocked.resume.set()
        await asyncio.wait_for(blocked.finished.wait(), 0.5)
        assert await manager.broadcast("fresh") == 1
        assert blocked.sent == ["initial", "fresh"]
    finally:
        await manager.shutdown()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_disconnect_and_shutdown_collect_a_blocked_send(shutdown: bool) -> None:
    manager = ConnectionManager(send_timeout_seconds=0.02)
    blocked = BlockedWebSocket()
    disconnected = await manager.connect(blocked)
    assert await manager.broadcast("blocked") == 0
    if shutdown:
        await manager.shutdown()
    else:
        await manager.disconnect(blocked)

    assert disconnected.is_set()
    assert blocked.finished.is_set()
    assert manager.connection_count == 0
    assert await manager.broadcast("after cleanup") == 0


async def test_failed_send_notifies_stream_cleanup() -> None:
    manager = ConnectionManager()
    broken = FakeWebSocket(working=False)
    disconnected = await manager.connect(broken)

    assert await manager.send(broken, "initial") is False
    assert disconnected.is_set()
    assert manager.connection_count == 0


async def test_cache_generation_continues_while_a_client_is_blocked(monkeypatch) -> None:
    from videre.backend.cache import refresh

    manager = ConnectionManager(send_timeout_seconds=0.02)
    blocked, healthy = BlockedWebSocket(), FakeWebSocket()
    await manager.connect(blocked)
    await manager.connect(healthy)
    generated = 0
    third_delivery = asyncio.Event()

    async def generate(*args) -> int:
        nonlocal generated
        generated += 1
        return 1

    async def deliver() -> None:
        await manager.broadcast(str(generated))
        if generated >= 3:
            third_delivery.set()

    monkeypatch.setattr(refresh, "refresh_once", generate)
    task = asyncio.create_task(refresh.run_cache_refresh(None, None, 0.001, on_refresh=deliver))
    try:
        await asyncio.wait_for(third_delivery.wait(), 0.5)
        assert generated >= 3
        assert healthy.sent[:3] == ["1", "2", "3"]
        assert blocked.send_calls == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await manager.shutdown()


class RoutedWebSocket(FakeWebSocket):
    def __init__(self, manager: ConnectionManager, redis: CountingRedis, *, accept_fails: bool = False) -> None:
        super().__init__()
        self.app = SimpleNamespace(state=SimpleNamespace(
            connection_manager=manager, redis_client=redis, settings=Settings(),
        ))
        self.client = SimpleNamespace(host="10.0.0.1")
        self.receiving = asyncio.Event()
        self.peer_disconnected = asyncio.Event()
        self.receive_finished = asyncio.Event()
        self.closed = False
        self.accept_fails = accept_fails

    async def accept(self) -> None:
        if self.accept_fails:
            raise ConnectionError("accept failed")
        await super().accept()

    async def receive_text(self) -> str:
        self.receiving.set()
        try:
            await self.peer_disconnected.wait()
            raise WebSocketDisconnect()
        finally:
            self.receive_finished.set()

    async def close(self, code: int) -> None:
        self.closed = True


@pytest.mark.parametrize("reason", ["peer", "send", "cancel", "shutdown"])
async def test_stream_releases_quota_and_receiver_on_disconnect(reason: str) -> None:
    from videre.backend.routes.stream import cluster_health_stream

    manager, redis = ConnectionManager(send_timeout_seconds=0.02), CountingRedis()
    websocket = RoutedWebSocket(manager, redis)
    task = asyncio.create_task(cluster_health_stream(websocket))
    await asyncio.wait_for(websocket.receiving.wait(), 0.5)
    if reason == "peer":
        websocket.peer_disconnected.set()
    elif reason == "send":
        websocket.working = False
        assert await manager.broadcast("failed") == 0
    elif reason == "cancel":
        task.cancel()
    else:
        await manager.shutdown()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 0.5)

    assert websocket.receive_finished.is_set()
    assert manager.connection_count == 0
    assert redis.counters[connection_key("10.0.0.1")] == 0
    if reason in ("send", "shutdown"):
        assert websocket.closed


async def test_failed_accept_releases_acquired_quota() -> None:
    from videre.backend.routes.stream import cluster_health_stream

    manager, redis = ConnectionManager(), CountingRedis()
    websocket = RoutedWebSocket(manager, redis, accept_fails=True)
    await cluster_health_stream(websocket)

    assert manager.connection_count == 0
    assert redis.counters[connection_key("10.0.0.1")] == 0
