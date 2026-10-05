import asyncio
import time

import pytest

from videre.backend.ai import retrieval
from videre.backend.ai.context import LokiContext, PostgresContext, PrometheusContext
from videre.backend.settings import Settings
from videre.database.tables import FailureEntityTable


class NullSessionFactory:
    def __call__(self) -> "NullSessionFactory":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *arguments: object) -> None:
        return None


def patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    postgres_delay: float = 0.0,
    prometheus_delay: float = 0.0,
    loki_delay: float = 0.0,
    prometheus_error: Exception | None = None,
) -> None:
    async def fake_postgres(session, entity_type, entity_id):
        await asyncio.sleep(postgres_delay)
        return PostgresContext()

    async def fake_prometheus(client, base_url, entity_type, entity_id, *, window_minutes):
        await asyncio.sleep(prometheus_delay)
        if prometheus_error is not None:
            raise prometheus_error
        return PrometheusContext(window_minutes=window_minutes)

    async def fake_resolve(session, entity_type, entity_id):
        return ["query"]

    async def fake_logs(client, base_url, queries, *, window_minutes, line_limit):
        await asyncio.sleep(loki_delay)
        return LokiContext(queries=queries, window_minutes=window_minutes)

    monkeypatch.setattr(retrieval, "load_postgres_context", fake_postgres)
    monkeypatch.setattr(retrieval, "query_metrics", fake_prometheus)
    monkeypatch.setattr(retrieval, "resolve_queries", fake_resolve)
    monkeypatch.setattr(retrieval, "query_logs", fake_logs)


async def assemble(settings: Settings) -> object:
    return await retrieval.assemble_failure_context(
        NullSessionFactory(), None, settings, FailureEntityTable.GPU, "gpu-1-2"
    )


async def test_all_three_sources_are_assembled(monkeypatch) -> None:
    """A healthy retrieval fills all three sections and reports nothing degraded."""

    patch_sources(monkeypatch)
    context = await assemble(Settings())
    assert context.postgres is not None
    assert context.prometheus is not None
    assert context.logs is not None
    assert context.degraded_sources == []


async def test_sources_run_concurrently(monkeypatch) -> None:
    """The three sources are queried in parallel, so total time tracks the slowest, not the sum."""

    patch_sources(monkeypatch, postgres_delay=0.2, prometheus_delay=0.2, loki_delay=0.2)
    started = time.monotonic()
    await assemble(Settings())
    assert time.monotonic() - started < 0.4


async def test_a_slow_source_degrades_to_none(monkeypatch) -> None:
    """A source exceeding its timeout is dropped and named, leaving the others intact."""

    patch_sources(monkeypatch, prometheus_delay=0.5)
    context = await assemble(Settings(ai_source_timeout_seconds=0.05))
    assert context.prometheus is None
    assert context.postgres is not None and context.logs is not None
    assert context.degraded_sources == ["prometheus"]


async def test_a_failing_source_degrades_to_none(monkeypatch) -> None:
    """A source that raises is dropped rather than failing the whole retrieval."""

    patch_sources(monkeypatch, prometheus_error=RuntimeError("connection refused"))
    context = await assemble(Settings())
    assert context.prometheus is None
    assert context.degraded_sources == ["prometheus"]


async def test_the_entity_is_recorded_on_the_context(monkeypatch) -> None:
    """The assembled context carries the entity it was built for."""

    patch_sources(monkeypatch)
    context = await assemble(Settings())
    assert (context.entity_type, context.entity_id) == (FailureEntityTable.GPU, "gpu-1-2")


async def test_job_database_and_aggregate_metrics_reach_prompt(session):
    from datetime import UTC, datetime

    from httpx2 import AsyncClient, MockTransport, Response

    from test_ai_fingerprint import seed
    from test_ai_postgres_source import failure
    from test_event_mapping import sample_job
    from videre.backend.ai.context import FailureContext
    from videre.backend.ai.postgres_source import load_postgres_context
    from videre.backend.ai.prometheus_source import query_metrics
    from videre.backend.ai.prompt import build_prompt
    from videre.backend.persistence.event_mapping import apply_event
    from videre.event_types import LifecycleEventType
    from videre.events import JobEventMessage, Topic

    await seed(session)
    job = sample_job()
    job.id, job.assigned_node_ids = "job-other", []
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=job,
    ))
    gpu_fault = failure("observed-gpu-fault")
    gpu_fault.root_cause_tag = "gpu_xid_error"
    job_fault = failure("correlated-job-timeout", "job", "job-other")
    job_fault.root_cause_tag = "job_timeout"
    session.add_all([gpu_fault, job_fault])
    await session.flush()
    postgres = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    async with AsyncClient(transport=MockTransport(lambda request: Response(200, json={
        "status": "success", "data": {"result": []},
    }))) as client:
        metrics = await query_metrics(client, "http://prometheus", FailureEntityTable.JOB, "job-1", window_minutes=15)
    context = FailureContext(
        entity_type=FailureEntityTable.JOB, entity_id="job-1", generated_at=datetime.now(UTC),
        postgres=postgres, prometheus=metrics,
    )
    prompt = build_prompt(context, maximum_characters=24_000)
    assert "observed-gpu-fault" in prompt and "gpu_xid_error" in prompt
    assert "correlated-job-timeout" in prompt and "job_timeout" in prompt
    assert "not per-job measurements" in prompt
    assert len(prompt) <= 24_000
