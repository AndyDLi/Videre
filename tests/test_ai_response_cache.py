from datetime import UTC, datetime

import pytest

from videre.backend.ai import assistant
from videre.backend.ai.analysis import RootCauseAnalysis
from videre.backend.ai.assistant import analyze_entity
from videre.backend.ai.context import FailureContext
from videre.backend.ai.fingerprint import EntityFingerprint
from videre.backend.ai.rate_limit import RateLimitExceeded
from videre.backend.ai.response_cache import (
    cache_key,
    read_cached_analysis,
    write_cached_analysis,
)
from videre.backend.settings import Settings
from videre.database.tables import FailureEntityTable

ANALYSIS = RootCauseAnalysis(summary="GPU is throttling.", next_steps=["Check cooling."])


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.counters: dict[str, int] = {}
    
    async def get(self, key: str) -> str | None:
        return self.values.get(key)
    
    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex
    
    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]
    
    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return self.expiries.get(key, -2)


class NullSessionFactory:
    def __call__(self) -> "NullSessionFactory":
        return self
    
    async def __aenter__(self) -> None:
        return None
    
    async def __aexit__(self, *arguments: object) -> None:
        return None


class SpyAnalyst:
    def __init__(self) -> None:
        self.calls = 0
    
    async def analyze(self, context) -> RootCauseAnalysis:
        self.calls += 1
        return ANALYSIS


def make_fingerprint(
    entity_type: FailureEntityTable = FailureEntityTable.GPU,
    entity_id: str = "gpu-1-2",
    health_state: str = "DEGRADED",
    failure_ids: tuple[str, ...] = ("failure-a",),
) -> EntityFingerprint:
    return EntityFingerprint(
        entity_type=entity_type,
        entity_id=entity_id,
        health_state=health_state,
        unresolved_failure_ids=failure_ids,
    )


@pytest.fixture
def spies(monkeypatch):
    counts = {"assembled": 0, "limited": 0}
    
    async def fake_assemble(session_factory, http_client, settings, entity_type, entity_id):
        counts["assembled"] += 1
        return FailureContext(
            entity_type=entity_type, entity_id=entity_id, generated_at=datetime.now(UTC)
        )
    
    async def fake_enforce(redis_client, settings, client):
        counts["limited"] += 1
    
    monkeypatch.setattr(assistant, "assemble_failure_context", fake_assemble)
    monkeypatch.setattr(assistant, "enforce_rate_limit", fake_enforce)
    return counts


async def run(redis, analyst, fingerprint=None, settings=None):
    return await analyze_entity(
        NullSessionFactory(),
        redis,
        None,
        analyst,
        settings or Settings(),
        fingerprint or make_fingerprint(),
        "10.0.0.1",
    )


def test_the_key_carries_the_entity_and_a_digest() -> None:
    """The cache key names the entity and carries a digest of its situation."""

    key = cache_key(make_fingerprint())
    assert key.startswith("ai:resp:gpu:gpu-1-2:")
    assert len(key.split(":")[-1]) == 16


def test_the_same_situation_produces_the_same_key() -> None:
    """An unchanged situation produces the same key, which is what makes the cache hit at all."""

    assert cache_key(make_fingerprint()) == cache_key(make_fingerprint())


def test_a_changed_health_state_produces_a_new_key() -> None:
    """A health-state change produces a new key."""

    assert cache_key(make_fingerprint()) != cache_key(make_fingerprint(health_state="FAILED"))


def test_a_changed_failure_set_produces_a_new_key() -> None:
    """A newly raised failure produces a new key."""

    assert cache_key(make_fingerprint()) != cache_key(
        make_fingerprint(failure_ids=("failure-a", "failure-b"))
    )


def test_a_resolved_failure_produces_a_new_key() -> None:
    """Resolving a failure produces a new key."""

    assert cache_key(make_fingerprint()) != cache_key(make_fingerprint(failure_ids=()))


def test_different_entities_never_share_a_key() -> None:
    """Two different entities never collide on one cache key."""

    assert cache_key(make_fingerprint(entity_id="gpu-1-2")) != cache_key(
        make_fingerprint(entity_id="gpu-1-3")
    )
    assert cache_key(make_fingerprint(FailureEntityTable.NODE, "shared")) != cache_key(
        make_fingerprint(FailureEntityTable.JOB, "shared")
    )


async def test_a_written_analysis_reads_back() -> None:
    """An analysis written to the cache reads back intact."""

    redis, fingerprint = FakeRedis(), make_fingerprint()
    await write_cached_analysis(redis, fingerprint, ANALYSIS, 420)
    assert await read_cached_analysis(redis, fingerprint) == ANALYSIS


async def test_an_absent_key_is_a_miss() -> None:
    """An absent key is a miss rather than an error."""

    assert await read_cached_analysis(FakeRedis(), make_fingerprint()) is None


async def test_the_ttl_is_applied() -> None:
    """The configured TTL is applied to every cached analysis."""

    redis, fingerprint = FakeRedis(), make_fingerprint()
    await write_cached_analysis(redis, fingerprint, ANALYSIS, 420)
    assert redis.expiries[cache_key(fingerprint)] == 420


async def test_an_unreadable_entry_is_a_miss() -> None:
    """A corrupt cache entry is treated as a miss rather than crashing the request."""

    redis, fingerprint = FakeRedis(), make_fingerprint()
    redis.values[cache_key(fingerprint)] = '{"unexpected": true}'
    assert await read_cached_analysis(redis, fingerprint) is None


async def test_a_cache_hit_skips_assembly_gemini_and_the_rate_limiter(spies) -> None:
    """A cache hit skips context assembly, the rate limiter, and the model call entirely."""

    redis, analyst, fingerprint = FakeRedis(), SpyAnalyst(), make_fingerprint()
    await write_cached_analysis(redis, fingerprint, ANALYSIS, 420)
    
    result = await run(redis, analyst, fingerprint)
    
    assert result.from_cache is True
    assert result.analysis == ANALYSIS
    assert (spies["assembled"], spies["limited"], analyst.calls) == (0, 0, 0)


async def test_a_cache_miss_assembles_limits_calls_and_caches(spies) -> None:
    """A miss checks the limiter, assembles context, calls the model, and caches the result."""

    redis, analyst, fingerprint = FakeRedis(), SpyAnalyst(), make_fingerprint()
    
    result = await run(redis, analyst, fingerprint)
    
    assert result.from_cache is False
    assert (spies["assembled"], spies["limited"], analyst.calls) == (1, 1, 1)
    assert await read_cached_analysis(redis, fingerprint) == ANALYSIS


async def test_a_second_request_for_the_same_situation_hits(spies) -> None:
    """A repeat request for an unchanged situation is served from cache."""

    redis, analyst, fingerprint = FakeRedis(), SpyAnalyst(), make_fingerprint()
    
    await run(redis, analyst, fingerprint)
    second = await run(redis, analyst, fingerprint)
    
    assert second.from_cache is True
    assert analyst.calls == 1


async def test_a_changed_situation_misses_within_the_ttl(spies) -> None:
    """A genuinely changed situation misses even inside the TTL window."""

    redis, analyst = FakeRedis(), SpyAnalyst()
    
    await run(redis, analyst, make_fingerprint(health_state="DEGRADED"))
    second = await run(redis, analyst, make_fingerprint(health_state="FAILED"))
    
    assert second.from_cache is False
    assert analyst.calls == 2


async def test_a_rate_limited_miss_never_calls_gemini_or_caches(monkeypatch) -> None:
    """A rate-limited miss never reaches the model and stores nothing."""

    async def reject(redis_client, settings, client):
        raise RateLimitExceeded("global per-day", 400, 3600)
    
    async def fake_assemble(session_factory, http_client, settings, entity_type, entity_id):
        return FailureContext(
            entity_type=entity_type, entity_id=entity_id, generated_at=datetime.now(UTC)
        )
    
    monkeypatch.setattr(assistant, "enforce_rate_limit", reject)
    monkeypatch.setattr(assistant, "assemble_failure_context", fake_assemble)
    redis, analyst, fingerprint = FakeRedis(), SpyAnalyst(), make_fingerprint()
    
    with pytest.raises(RateLimitExceeded):
        await run(redis, analyst, fingerprint)
    
    assert analyst.calls == 0
    assert await read_cached_analysis(redis, fingerprint) is None


@pytest.mark.parametrize("change,hit", [
    ("gpu_health", False), ("node_health", False), ("failure", False),
    ("resolution", False), ("assignment", False), ("correlation", False),
    ("metric", True), ("unrelated", True),
])
async def test_database_evidence_changes_control_cache_reuse(session, change, hit):
    from datetime import UTC, datetime

    from sqlalchemy import delete, update

    from test_ai_fingerprint import seed
    from test_ai_postgres_source import add_node, failure
    from videre.backend.ai.fingerprint import load_fingerprint
    from videre.database.tables import FailureRecord, Gpu, JobNodeAssignment, Node

    await seed(session)
    await add_node(session, "node-other")
    session.add(failure("direct"))
    if change in {"resolution", "correlation"}:
        session.add(failure("related", "node", "node-other"))
    await session.flush()
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert before is not None
    redis = FakeRedis()
    await write_cached_analysis(redis, before, ANALYSIS, 420)
    if change == "gpu_health":
        await session.execute(update(Gpu).values(health_state="FAILED"))
    elif change == "node_health":
        await session.execute(update(Node).where(Node.id == "node-0").values(health_state="NOT_READY"))
    elif change == "failure":
        session.add(failure("new", "node", "node-other"))
    elif change == "resolution":
        await session.execute(update(FailureRecord).where(FailureRecord.id == "related")
            .values(resolved_at=datetime.now(UTC)))
    elif change == "assignment":
        await session.execute(delete(JobNodeAssignment))
        session.add(JobNodeAssignment(job_id="job-1", node_id="node-other"))
    elif change == "correlation":
        await session.execute(update(FailureRecord).where(FailureRecord.id == "related")
            .values(correlation_id="disconnected"))
    elif change == "metric":
        await session.execute(update(Gpu).values(utilization_percentage=99, temperature_celsius=88))
    else:
        session.add(failure("unrelated", "node", "node-other", "other-incident"))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert after is not None
    cached = await read_cached_analysis(redis, after)
    assert (cached == ANALYSIS) == hit


async def test_legacy_fingerprint_response_is_not_reused():
    import hashlib
    fingerprint = make_fingerprint()
    legacy = "gpu:gpu-1-2:DEGRADED:failure-a"
    digest = hashlib.sha256(legacy.encode()).hexdigest()[:16]
    redis = FakeRedis()
    redis.values[f"ai:resp:gpu:gpu-1-2:{digest}"] = ANALYSIS.model_dump_json()
    assert await read_cached_analysis(redis, fingerprint) is None


async def test_scheduler_cap_changes_keep_the_cached_diagnosis(session):
    from test_ai_fingerprint import seed
    from videre.backend.ai.fingerprint import load_fingerprint
    from videre.backend.ai.postgres_source import load_postgres_context
    from videre.database.tables import SchedulerEventRecord

    await seed(session)
    now = datetime.now(UTC)
    def event(index):
        return SchedulerEventRecord(
            id=f"scheduler-{index:02}", event_id=f"scheduler-{index:02}", type="QUEUEING_DELAY", timestamp=now,
            related_job_id="job-1", related_node_id="node-0", delay_seconds=float(index), reason="queued",
        )
    session.add_all([event(index) for index in range(20)])
    await session.flush()
    before = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    assert before is not None
    redis = FakeRedis()
    await write_cached_analysis(redis, before, ANALYSIS, 420)
    session.add(event(20))
    await session.flush()
    after = await load_fingerprint(session, FailureEntityTable.JOB, "job-1")
    context = await load_postgres_context(session, FailureEntityTable.JOB, "job-1")
    assert after is not None and context is not None
    assert "scheduler_events" in context.truncated_sections
    assert await read_cached_analysis(redis, after) == ANALYSIS
