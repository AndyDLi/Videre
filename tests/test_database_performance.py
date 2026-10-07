import asyncio
import os

import pytest
from prometheus_client import CollectorRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_measured_sessions_release_connections_and_record_contention():
    from videre.backend.metrics import performance

    assert callable(getattr(performance, "measured_session_factory", None))
    database_url = os.environ.get("VIDERE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set VIDERE_TEST_DATABASE_URL for PostgreSQL performance tests")
    registry = CollectorRegistry()
    metrics = performance.DatabaseMetrics(registry)
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    factory = performance.measured_session_factory(engine, metrics)
    try:
        async with factory() as first, first.begin():
            assert (await first.scalar(text("SELECT 7"))) == 7
            assert registry.get_sample_value("videre_database_connections_checked_out") == 1
            async def competitor():
                async with factory() as second, second.begin():
                    return await second.scalar(text("SELECT 8"))
            waiting = asyncio.create_task(competitor())
            await asyncio.sleep(0.12)
            assert not waiting.done()
        assert await asyncio.wait_for(waiting, 2) == 8
        assert registry.get_sample_value("videre_database_connections_checked_out") == 0
        assert registry.get_sample_value(
            "videre_database_acquisition_seconds_sum", {"outcome": "success"}
        ) >= 0.1
        async with factory() as session:
            with pytest.raises(Exception, match="division by zero"):
                await session.execute(text("SELECT 1 / 0"))
        assert registry.get_sample_value("videre_database_connections_checked_out") == 0
        assert registry.get_sample_value(
            "videre_database_query_seconds_count", {"operation": "select", "outcome": "error"}
        ) == 1
        async with factory() as first:
            await first.execute(text("SELECT 1"))
            waiting = asyncio.create_task(competitor())
            await asyncio.sleep(0.02)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        assert registry.get_sample_value("videre_database_connections_checked_out") == 0
        async with factory() as session, session.begin():
            assert await session.scalar(text("SELECT 9")) == 9
        assert registry.get_sample_value("videre_database_connections_checked_out") == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_cache_metrics_count_valid_missing_invalid_and_failed_reads():
    from redis.asyncio import Redis

    from videre.backend.ai.analysis import RootCauseAnalysis
    from videre.backend.ai.fingerprint import EntityFingerprint
    from videre.backend.ai.response_cache import cache_key, read_cached_analysis, write_cached_analysis
    from videre.backend.metrics.performance import AI_CACHE_GET, AI_CACHE_READS
    from videre.database.tables import FailureEntityTable

    redis_url = os.environ.get("VIDERE_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set VIDERE_TEST_REDIS_URL for real Redis metric tests")
    client = Redis.from_url(redis_url, decode_responses=True)
    fingerprint = EntityFingerprint(
        entity_type=FailureEntityTable.NODE, entity_id="metric-test-owned",
        health_state="READY", unresolved_failure_ids=(),
    )
    key = cache_key(fingerprint)
    before = {label: AI_CACHE_READS.labels(label)._value.get() for label in ("hit", "miss", "invalid")}
    count_before = AI_CACHE_GET.labels("success")._sum.get()
    try:
        await client.delete(key)
        assert await read_cached_analysis(client, fingerprint) is None
        analysis = RootCauseAnalysis(summary="Observed failure", next_steps=["Check cooling"])
        await write_cached_analysis(client, fingerprint, analysis, 60)
        assert await read_cached_analysis(client, fingerprint) == analysis
        await client.set(key, "not JSON", ex=60)
        assert await read_cached_analysis(client, fingerprint) is None
        for label in before:
            assert AI_CACHE_READS.labels(label)._value.get() - before[label] == 1
        assert AI_CACHE_GET.labels("success")._sum.get() > count_before
        class UnavailableRedis:
            async def get(self, requested_key):
                raise ConnectionError("owned test store unavailable")
        error_before = AI_CACHE_GET.labels("error")._sum.get()
        with pytest.raises(ConnectionError, match="store unavailable"):
            await read_cached_analysis(UnavailableRedis(), fingerprint)
        assert AI_CACHE_GET.labels("error")._sum.get() > error_before
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.asyncio
async def test_instrumentation_preserves_explicit_statement_binding():
    from videre.backend.metrics.performance import DatabaseMetrics, measured_session_factory

    database_url = os.environ.get("VIDERE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set VIDERE_TEST_DATABASE_URL for PostgreSQL performance tests")
    default = create_async_engine(database_url)
    alternative = create_async_engine(database_url)
    factory = measured_session_factory(default, DatabaseMetrics(CollectorRegistry()))
    try:
        async with factory() as session:
            assert await session.scalar(text("SELECT 11"), bind_arguments={"bind": alternative.sync_engine}) == 11
            assert default.sync_engine.pool.checkedout() == 0
            assert alternative.sync_engine.pool.checkedout() == 1
        assert alternative.sync_engine.pool.checkedout() == 0
    finally:
        await default.dispose()
        await alternative.dispose()
