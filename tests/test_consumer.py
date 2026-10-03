import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiokafka import TopicPartition
from aiokafka.errors import CommitFailedError
from prometheus_client import REGISTRY
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from test_event_mapping import (
    persisted_rows,
    run_message,
    sample_gpu,
    sample_job,
    sample_node,
    seed_previous_run,
)
from videre.backend.persistence import consumer as consumer_module
from videre.backend.persistence.event_mapping import EventDisposition, apply_event
from videre.backend.settings import Settings
from videre.database.tables import FailureRecord, Job, JobNodeAssignment, Node, SchedulerEventRecord
from videre.event_types import EventType
from videre.events import JobEventMessage, NodeEventMessage, SchedulerEventMessage, Topic
from videre.models import GpuHealthState, JobState, NodeHealthState, SchedulerEvent, SchedulerEventType

HANDLED = TopicPartition("node-events", 0)
OTHER_PARTITION = TopicPartition("node-events", 1)
OTHER_TOPIC = TopicPartition("job-events", 0)
UNBOOKMARKED = TopicPartition("gpu-metrics", 2)


def node_message():
    return NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value,
        payload=sample_node(NodeHealthState.NOT_READY),
    )


def kafka_record(message=None, *, topic="node-events", partition=0, offset=10):
    if message is None:
        message = node_message()
    return SimpleNamespace(
        topic=topic, partition=partition, offset=offset,
        value=message.model_dump_json().encode(),
    )


def memory_sessions(trace, transaction_error=None):
    class Session:
        @asynccontextmanager
        async def begin(self):
            trace.append("begin")
            try:
                yield
                if transaction_error is not None:
                    raise transaction_error
            except BaseException:
                trace.append("rollback")
                raise
            else:
                trace.append("db_commit")

    @asynccontextmanager
    async def factory():
        yield Session()

    return factory


class RecordingConsumer:
    def __init__(self, trace=None, commit_failures=0):
        self.trace = trace if trace is not None else []
        self.positions = {HANDLED: 99, OTHER_PARTITION: 15, OTHER_TOPIC: 37, UNBOOKMARKED: 41}
        self.bookmarks = {HANDLED: 10, OTHER_PARTITION: 12, OTHER_TOPIC: 30}
        self.commit_requests = []
        self.commit_failures = commit_failures
        self.before_commit = lambda: None

    async def commit(self, offsets=None):
        self.before_commit()
        self.trace.append("kafka_commit")
        submitted = dict(self.positions if offsets is None else offsets)
        self.commit_requests.append(submitted)
        if self.commit_failures:
            self.commit_failures -= 1
            raise CommitFailedError()
        self.bookmarks.update(submitted)


class RetainedBroker:
    """Track delivered positions separately from durable group bookmarks."""

    def __init__(self, records, *, bookmarked=True, disconnect_after_first=False, commit_failures=0):
        self.records = records
        self.bookmarks = {HANDLED: 10} if bookmarked else {}
        self.instances = []
        self.deliveries = []
        self.trace = []
        self.disconnect_after_first = disconnect_after_first
        self.commit_failures = commit_failures
        self.persisted = []

    def consumer(self, *topics, **options):
        broker = self

        class Consumer:
            def __init__(self):
                self.generation = len(broker.instances) + 1
                self.stopped = False
                self.delivered = 0
                self.positions = {}

            async def start(self):
                # The first record arrives after assignment of this fresh group.
                available = broker.records if self.generation > 1 else []
                reset = 10 if options["auto_offset_reset"] == "earliest" else (
                    available[-1].offset + 1 if available else 10
                )
                self.positions[HANDLED] = broker.bookmarks.get(HANDLED, reset)
                broker.trace.append(("start", self.generation))

            async def stop(self):
                self.stopped = True
                broker.trace.append(("stop", self.generation))

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.generation == 1 and self.delivered and broker.disconnect_after_first:
                    raise RuntimeError("connection lost before first bookmark")
                for record in broker.records:
                    if record.offset >= self.positions[HANDLED]:
                        self.positions[HANDLED] = record.offset + 1
                        self.delivered += 1
                        broker.deliveries.append((self.generation, record.offset))
                        return record
                # End the otherwise infinite background task deterministically.
                raise asyncio.CancelledError()

            async def commit(self, offsets=None):
                if broker.commit_failures:
                    broker.commit_failures -= 1
                    raise CommitFailedError()
                broker.bookmarks.update(self.positions if offsets is None else offsets)

        instance = Consumer()
        self.instances.append(instance)
        return instance

    async def backoff(self, delay):
        assert self.instances[-1].stopped
        assert delay == 5.0
        self.trace.append(("backoff", self.instances[-1].generation))


@pytest.mark.parametrize("failure_phase", ["apply", "transaction_exit"])
async def test_persistence_failure_escapes_without_metrics_or_offset_commit(monkeypatch, caplog, failure_phase):
    error = RuntimeError("transient database failure")
    trace = []
    consumer = RecordingConsumer(trace)
    sessions = memory_sessions(trace, error if failure_phase == "transaction_exit" else None)
    apply = AsyncMock(side_effect=error if failure_phase == "apply" else None)
    metrics = Mock()
    monkeypatch.setattr(consumer_module, "apply_event", apply)
    monkeypatch.setattr(consumer_module, "record_event", metrics)

    with pytest.raises(RuntimeError) as caught:
        await consumer_module.handle_record(sessions, consumer, kafka_record())

    assert caught.value is error
    assert trace == ["begin", "rollback"]
    assert consumer.commit_requests == []
    metrics.assert_not_called()
    failure = next(record for record in caplog.records if record.message == "persistence failed")
    assert (failure.topic, failure.partition, failure.offset) == ("node-events", 0, 10)


async def test_success_commits_record_offset_only_after_transaction_and_metrics(monkeypatch):
    trace = []
    consumer = RecordingConsumer(trace)
    async def traced_apply(*args):
        trace.append("apply")
        return EventDisposition.APPLIED

    monkeypatch.setattr(consumer_module, "apply_event", traced_apply)
    monkeypatch.setattr(consumer_module, "record_event", lambda *_: trace.append("metrics"))

    await consumer_module.handle_record(memory_sessions(trace), consumer, kafka_record())

    assert trace == ["begin", "apply", "db_commit", "metrics", "kafka_commit"]
    assert UNBOOKMARKED not in consumer.bookmarks
    assert consumer.commit_requests == [{HANDLED: 11}]
    assert consumer.bookmarks == {HANDLED: 11, OTHER_PARTITION: 12, OTHER_TOPIC: 30}


@pytest.mark.parametrize(
    ("topic", "value"),
    [("node-events", b"not json"), ("node-events", b"{}"), ("unknown-topic", b"{}"), ("node-events", None)],
)
async def test_malformed_rejection_logs_position_before_committing_only_its_partition(
    monkeypatch, caplog, topic, value,
):
    consumer = RecordingConsumer()
    record = SimpleNamespace(topic=topic, partition=0, offset=10, value=value)
    apply = AsyncMock(return_value=EventDisposition.APPLIED)
    metrics = Mock()
    monkeypatch.setattr(consumer_module, "apply_event", apply)
    monkeypatch.setattr(consumer_module, "record_event", metrics)

    def check_log_before_commit():
        warning = next(entry for entry in caplog.records if entry.message == "skipping malformed message")
        assert (warning.topic, warning.partition, warning.offset) == (topic, 0, 10)
        assert warning.error

    consumer.before_commit = check_log_before_commit
    with caplog.at_level(logging.WARNING, logger="videre.backend.consumer"):
        await consumer_module.handle_record(Mock(side_effect=AssertionError("unexpected session")), consumer, record)

    assert UNBOOKMARKED not in consumer.bookmarks
    assert consumer.commit_requests == [{TopicPartition(topic, 0): 11}]
    assert consumer.bookmarks[OTHER_PARTITION] == 12
    assert consumer.bookmarks[OTHER_TOPIC] == 30
    apply.assert_not_awaited()
    metrics.assert_not_called()


@pytest.mark.parametrize("bookmarked", [True, False])
async def test_database_failure_reconnects_and_recovers_retained_record(monkeypatch, bookmarked):
    records = [kafka_record(), kafka_record(offset=11)]
    broker = RetainedBroker(records, bookmarked=bookmarked, disconnect_after_first=not bookmarked)
    if bookmarked:
        broker.bookmarks[HANDLED] = 11  # Earlier retained history must not override this bookmark.
    attempts = 0

    async def persist(session, topic, message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient database failure")
        broker.persisted.append(message.event_id)
        return EventDisposition.APPLIED

    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", broker.consumer)
    monkeypatch.setattr(consumer_module, "apply_event", persist)
    monkeypatch.setattr(consumer_module, "record_event", Mock())
    monkeypatch.setattr(consumer_module.asyncio, "sleep", broker.backoff)

    with pytest.raises(asyncio.CancelledError):
        await consumer_module.run_consumer(memory_sessions([]), Settings())

    assert broker.deliveries == ([(1, 11), (2, 11)] if bookmarked else [(1, 10), (2, 10), (2, 11)])
    replayed = records[1:] if bookmarked else records
    assert broker.persisted == [NodeEventMessage.model_validate_json(record.value).event_id for record in replayed]
    assert broker.bookmarks == {HANDLED: 12}
    assert broker.trace[:4] == [("start", 1), ("stop", 1), ("backoff", 1), ("start", 2)]
    assert all(instance.stopped for instance in broker.instances)


@pytest.mark.parametrize("malformed", [False, True])
async def test_offset_commit_failure_reconnects_and_replays_same_record(monkeypatch, malformed):
    record = kafka_record()
    if malformed:
        record.value = b"not json"
    broker = RetainedBroker([record], commit_failures=1)
    apply = AsyncMock(return_value=EventDisposition.APPLIED)
    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", broker.consumer)
    monkeypatch.setattr(consumer_module, "apply_event", apply)
    monkeypatch.setattr(consumer_module, "record_event", Mock())
    monkeypatch.setattr(consumer_module.asyncio, "sleep", broker.backoff)

    with pytest.raises(asyncio.CancelledError):
        await consumer_module.run_consumer(memory_sessions([]), Settings())

    assert broker.deliveries == [(1, 10), (2, 10)]
    assert broker.bookmarks == {HANDLED: 11}
    assert apply.await_count == (0 if malformed else 2)
    assert all(instance.stopped for instance in broker.instances)


async def test_shutdown_cancels_real_backoff_without_constructing_another_consumer(monkeypatch):
    broker = RetainedBroker([kafka_record()])
    waiting = asyncio.Event()
    real_sleep = asyncio.sleep

    async def observed_sleep(delay):
        waiting.set()
        await real_sleep(delay)

    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", broker.consumer)
    monkeypatch.setattr(consumer_module, "apply_event", AsyncMock(side_effect=RuntimeError("database unavailable")))
    monkeypatch.setattr(consumer_module.asyncio, "sleep", observed_sleep)
    task = asyncio.create_task(consumer_module.run_consumer(memory_sessions([]), Settings()))
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        assert broker.instances[0].stopped
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    assert len(broker.instances) == 1


async def test_shutdown_during_persistence_stops_consumer_without_offset_commit(monkeypatch):
    broker = RetainedBroker([kafka_record()])
    applying = asyncio.Event()

    async def persist(*args):
        applying.set()
        await asyncio.Future()

    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", broker.consumer)
    monkeypatch.setattr(consumer_module, "apply_event", persist)
    task = asyncio.create_task(consumer_module.run_consumer(memory_sessions([]), Settings()))
    try:
        await asyncio.wait_for(applying.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    assert broker.instances[0].stopped
    assert broker.bookmarks == {HANDLED: 10}


@pytest.mark.parametrize("domain", ["node", "scheduler", "job"])
async def test_database_rows_deduplicate_after_failed_offset_commit(session, domain):
    if domain == "node":
        message = node_message()
        topic = Topic.NODE_EVENTS
        metric_name = "videre_node_failure_events_total"
        labels = {"node_id": "node-0", "failure_mode": message.event_type}
        expected = {Node: 1, Job: 0, JobNodeAssignment: 0, SchedulerEventRecord: 0}
    elif domain == "scheduler":
        message = SchedulerEventMessage(
            event_type=EventType.CAPACITY_FRAGMENTATION.value,
            payload=SchedulerEvent(
                id="scheduler-replay", type=SchedulerEventType.QUEUEING_DELAY,
                node_id="node-0", delay_seconds=42.0, reason="capacity fragmented",
            ),
        )
        topic = Topic.SCHEDULER_EVENTS
        metric_name = "videre_capacity_events_total"
        labels = {"event_type": message.event_type}
        expected = {Node: 1, Job: 0, JobNodeAssignment: 0, SchedulerEventRecord: 1}
    else:
        message = JobEventMessage(
            event_type=EventType.JOB_OOM_KILL.value, payload=sample_job(JobState.FAILED),
        )
        topic = Topic.JOB_EVENTS
        metric_name = "videre_job_failures_total"
        labels = {"failure_mode": message.event_type}
        expected = {Node: 1, Job: 1, JobNodeAssignment: 1, SchedulerEventRecord: 0}
    record = kafka_record(message, topic=topic.value, partition=2)
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    consumer = RecordingConsumer(commit_failures=1)
    before = REGISTRY.get_sample_value(metric_name, labels) or 0.0

    with pytest.raises(CommitFailedError):
        await consumer_module.handle_record(factory, consumer, record)
    assert TopicPartition(topic.value, 2) not in consumer.bookmarks
    await consumer_module.handle_record(factory, consumer, record)

    expected[FailureRecord] = 1
    for table, count in expected.items():
        stored = (await session.execute(select(func.count()).select_from(table))).scalar_one()
        assert stored == count
    assert consumer.commit_requests == [{TopicPartition(topic.value, 2): 11}] * 2
    assert consumer.bookmarks[TopicPartition(topic.value, 2)] == 11
    assert consumer.bookmarks[OTHER_PARTITION] == 12
    assert REGISTRY.get_sample_value(metric_name, labels) == before + 2


@pytest.mark.parametrize("bookmarked", [True, False])
async def test_database_transaction_rolls_back_then_reconnect_persists_event(session, monkeypatch, bookmarked):
    record = kafka_record()
    broker = RetainedBroker([record], bookmarked=bookmarked, disconnect_after_first=not bookmarked)
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    real_apply = consumer_module.apply_event
    attempts = 0

    async def fail_after_writes(active_session, topic, message):
        nonlocal attempts
        attempts += 1
        disposition = await real_apply(active_session, topic, message)
        if attempts == 1:
            # A real PostgreSQL error after writes must roll back the entire transaction.
            await active_session.execute(text("SELECT 1 / 0"))
        return disposition

    async def check_rollback_before_retry(delay):
        assert (await session.execute(select(func.count()).select_from(Node))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(FailureRecord))).scalar_one() == 0
        assert broker.bookmarks == ({HANDLED: 10} if bookmarked else {})
        await broker.backoff(delay)

    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", broker.consumer)
    monkeypatch.setattr(consumer_module, "apply_event", fail_after_writes)
    monkeypatch.setattr(consumer_module.asyncio, "sleep", check_rollback_before_retry)

    with pytest.raises(asyncio.CancelledError):
        await consumer_module.run_consumer(factory, Settings())

    assert broker.deliveries == [(1, 10), (2, 10)]
    assert broker.bookmarks == {HANDLED: 11}
    assert (await session.execute(select(func.count()).select_from(Node))).scalar_one() == 1
    assert (await session.execute(select(func.count()).select_from(FailureRecord))).scalar_one() == 1

@pytest.mark.parametrize("disposition", [
    "stale_run", "legacy_after_boundary", "conflicting_run",
])
@pytest.mark.parametrize("commit_fails", [False, True])
async def test_run_rejection_logs_before_partition_commit_without_metrics(
    monkeypatch, caplog, disposition, commit_fails,
):
    trace = []
    consumer = RecordingConsumer(trace, commit_failures=int(commit_fails))
    metrics = Mock()
    monkeypatch.setattr(consumer_module, "apply_event", AsyncMock(return_value=EventDisposition(disposition)))
    monkeypatch.setattr(consumer_module, "record_event", metrics)
    message = run_message(Topic.NODE_EVENTS, 1)
    if disposition == "legacy_after_boundary":
        message = message.model_copy(update={"schema_version": 1, "simulation_run": None})
    record = kafka_record(message)
    def assert_logged_before_commit():
        logs = [item for item in caplog.records if item.message == "skipping simulation event"]
        assert len(logs) == 1
        log = logs[0]
        assert (log.topic, log.partition, log.offset, log.event_id) == (
            "node-events", 0, 10, message.event_id,
        )
        assert log.reason == disposition
        assert log.simulation_run == (
            message.simulation_run.model_dump(mode="json") if message.simulation_run is not None else None
        )
        assert trace == ["begin", "db_commit"]
    consumer.before_commit = assert_logged_before_commit
    if commit_fails:
        with pytest.raises(CommitFailedError):
            await consumer_module.handle_record(memory_sessions(trace), consumer, record)
    else:
        await consumer_module.handle_record(memory_sessions(trace), consumer, record)
    metrics.assert_not_called()
    assert consumer.commit_requests == [{HANDLED: 11}]
    assert consumer.bookmarks[OTHER_PARTITION] == 12 and consumer.bookmarks[OTHER_TOPIC] == 30
    assert UNBOOKMARKED not in consumer.bookmarks


async def test_boundary_commit_failure_replay_does_not_reset_new_run_state(session):
    await seed_previous_run(session)
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    message = run_message(
        Topic.NODE_EVENTS, 2, payload=sample_node(NodeHealthState.NOT_READY), event_type="node.disk_pressure",
    )
    record = kafka_record(message)
    consumer = RecordingConsumer(commit_failures=1)
    with pytest.raises(CommitFailedError):
        await consumer_module.handle_record(factory, consumer, record)
    await apply_event(session, Topic.JOB_EVENTS, run_message(Topic.JOB_EVENTS, 2))
    before = await persisted_rows(session)
    await consumer_module.handle_record(factory, consumer, record)
    assert await persisted_rows(session) == before
    assert consumer.commit_requests == [{HANDLED: 11}] * 2
    session.expire_all()
    assert (await session.get(Job, "job-run-2")).lifecycle_state == "RUNNING"
    assert (await session.get(Job, "old-running")).failure_reason == "simulation reset"


@pytest.mark.parametrize("topic,event_type,payload", [
    (Topic.NODE_EVENTS, "node.recovered", sample_node()),
    (Topic.GPU_METRICS, "gpu.recovered", sample_gpu()),
    (Topic.NODE_EVENTS, "node.kubelet_down", sample_node(NodeHealthState.NOT_READY)),
])
async def test_stale_records_leave_current_metrics_and_database_unchanged(session, topic, event_type, payload):
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    consumer = RecordingConsumer()
    await consumer_module.handle_record(factory, consumer, kafka_record(run_message(
        Topic.NODE_EVENTS, 2, payload=sample_node(NodeHealthState.NOT_READY), event_type="node.kubelet_down",
    )))
    await consumer_module.handle_record(factory, consumer, kafka_record(run_message(
        Topic.GPU_METRICS, 2, payload=sample_gpu().model_copy(update={"health_state": GpuHealthState.FAILED}),
        event_type="gpu.driver_crash",
    ), topic=Topic.GPU_METRICS.value))
    samples = [
        ("videre_node_health_state", {"node_id": "node-0", "state": "NOT_READY"}),
        ("videre_gpu_health_state", {"node_id": "node-0", "gpu_id": "gpu-0-0", "state": "FAILED"}),
        ("videre_node_failure_events_total", {"node_id": "node-0", "failure_mode": "node.kubelet_down"}),
    ]
    values = [REGISTRY.get_sample_value(name, labels) for name, labels in samples]
    before = await persisted_rows(session)
    await consumer_module.handle_record(factory, consumer, kafka_record(
        run_message(topic, 1, payload=payload, event_type=event_type), topic=topic.value, offset=11,
    ))
    assert await persisted_rows(session) == before
    assert [REGISTRY.get_sample_value(name, labels) for name, labels in samples] == values
    assert values[0:2] == [1.0, 1.0]
