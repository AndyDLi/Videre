"""Private benchmark fixture: real routes and stores, fixed data, no provider access."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx2
import uvicorn
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from videre.backend.ai.analysis import RootCauseAnalysis
from videre.backend.ai.fingerprint import load_fingerprint
from videre.backend.ai.response_cache import write_cached_analysis
from videre.backend.application import create_application
from videre.backend.cache.refresh import refresh_once, run_cache_refresh
from videre.backend.metrics.performance import measured_session_factory
from videre.backend.settings import Settings
from videre.database.tables import Cluster, FailureEntityTable, FailureRecord, Gpu, Job, JobNodeAssignment, Node


def refuse_provider(request=None):
    raise RuntimeError("External AI/source calls are forbidden in this fixture")


class NoProvider:
    async def analyze(self, context):
        refuse_provider()


async def prepare(factory, redis, settings):
    async with factory() as session, session.begin():
        if await session.get(Cluster, "benchmark") is None:
            session.add(Cluster(id="benchmark", name="Fixed request dataset"))
            await session.flush()
            for index in range(4):
                session.add(Node(
                    id=f"node-{index}", cluster_id="benchmark", cpu_cores=64, memory_gb=512, gpu_count=8,
                    health_state="READY", simulated_node_label=f"node-{index}",
                ))
            await session.flush()
            for index in range(32):
                session.add(Gpu(
                    id=f"gpu-{index}", node_id=f"node-{index // 8}", utilization_percentage=50,
                    temperature_celsius=65, memory_used_mb=10000, memory_total_mb=81920,
                    ecc_correctable_count=0, ecc_uncorrectable_count=0, xid_error_count=0,
                    health_state="DEGRADED" if index == 0 else "HEALTHY",
                ))
            for index in range(1000):
                session.add(Job(
                    id=f"job-{index:04d}", cluster_id="benchmark",
                    lifecycle_state="RUNNING" if index < 24 else "PENDING" if index < 32 else "COMPLETED",
                    requested_cpu_cores=1, requested_memory_gb=1, requested_gpu_count=1,
                ))
            await session.flush()
            session.add_all([
                JobNodeAssignment(job_id=f"job-{index:04d}", node_id=f"node-{index % 4}")
                for index in range(1000)
            ])
            session.add(FailureRecord(
                id="failure-gpu-0", event_id="failure-gpu-0", entity_type="gpu", entity_id="gpu-0",
                category="gpu", root_cause_tag="thermal", correlation_id="benchmark-chain",
                detected_at=datetime.now(UTC),
            ))
    async with factory() as session:
        fingerprint = await load_fingerprint(session, FailureEntityTable.NODE, "node-0")
        assert fingerprint is not None
        assert len((await session.scalars(select(Job.id))).all()) == 1000
    await write_cached_analysis(redis, fingerprint, RootCauseAnalysis(
        summary="Recorded GPU thermal failure on node-0. Exact GPU assignment to jobs is unknown.",
        next_steps=["Inspect gpu-0 cooling.", "Review related job failures."],
    ), settings.ai_cache_ttl_seconds)
    await refresh_once(factory, redis, settings.cache_refresh_interval_seconds)


def settings():
    required = {
        "VIDERE_POSTGRES_HOST": "videre-rps-postgres",
        "VIDERE_POSTGRES_DATABASE": "benchmark",
        "VIDERE_POSTGRES_USER": "videre_app",
        "VIDERE_REDIS_HOST": "videre-rps-redis",
    }
    if any(os.environ.get(key) != value for key, value in required.items()):
        raise SystemExit("Fixture requires explicitly selected disposable PostgreSQL and Redis hosts/role")
    return Settings(gemini_api_key=SecretStr(""))


@asynccontextmanager
async def benchmark_lifespan(app):
    configuration = settings()
    engine = create_async_engine(configuration.postgres_dsn, pool_size=5, max_overflow=5, pool_pre_ping=True)
    factory = measured_session_factory(engine)
    redis = Redis.from_url(configuration.redis_url, decode_responses=True)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(refuse_provider))
    app.state.session_factory = factory
    app.state.redis_client = redis
    app.state.http_client = http
    app.state.gemini_analyst = NoProvider()
    await prepare(factory, redis, configuration)
    refresh = asyncio.create_task(run_cache_refresh(factory, redis, configuration.cache_refresh_interval_seconds))
    try:
        yield
    finally:
        refresh.cancel()
        await asyncio.gather(refresh, return_exceptions=True)
        await http.aclose()
        await redis.aclose()
        await engine.dispose()


async def prime():
    configuration = settings()
    engine = create_async_engine(configuration.postgres_dsn)
    factory = measured_session_factory(engine)
    redis = Redis.from_url(configuration.redis_url, decode_responses=True)
    try:
        await prepare(factory, redis, configuration)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    import sys
    if os.environ.get("VIDERE_POSTGRES_DATABASE") != "benchmark":
        raise SystemExit("Fixture requires explicitly selected disposable database named benchmark")
    if "--prime-cache" in sys.argv:
        asyncio.run(prime())
    else:
        app = create_application(settings())
        app.router.lifespan_context = benchmark_lifespan
        uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
