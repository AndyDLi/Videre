"""
One combined FailureContext for one entity.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videre.database.tables import FailureEntityTable

from ..settings import Settings
from .context import FailureContext, LokiContext, PostgresContext, PrometheusContext
from .loki_source import query_logs, resolve_queries
from .postgres_source import load_postgres_context
from .prometheus_source import query_metrics

logger = logging.getLogger("videre.backend.ai")


async def _bounded[ResultT](name: str, awaitable: Awaitable[ResultT], timeout_seconds: float) -> ResultT | None:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("context source timed out", extra={"source": name, "timeout_seconds": timeout_seconds})
    except Exception as error:
        logger.warning("context source failed", extra={"source": name, "error": str(error)})
    return None


async def assemble_failure_context(
    session_factory: async_sessionmaker[AsyncSession],
    http_client: AsyncClient,
    settings: Settings,
    entity_type: FailureEntityTable,
    entity_id: str
) -> FailureContext:
    async def postgres_section() -> PostgresContext | None:
        async with session_factory() as session:
            return await load_postgres_context(session, entity_type, entity_id)
    
    async def prometheus_section() -> PrometheusContext:
        return await query_metrics(
            http_client,
            settings.prometheus_base_url,
            entity_type,
            entity_id,
            window_minutes=settings.ai_metric_window_minutes
        )
    
    async def loki_section() -> LokiContext:
        async with session_factory() as session:
            queries = await resolve_queries(session, entity_type, entity_id)
        return await query_logs(
            http_client,
            settings.loki_base_url,
            queries,
            window_minutes=settings.ai_log_window_minutes,
            line_limit=settings.ai_log_line_limit
        )
    
    timeout_seconds = settings.ai_source_timeout_seconds
    postgres, prometheus, logs = await asyncio.gather(
        _bounded("postgres", postgres_section(), timeout_seconds),
        _bounded("prometheus", prometheus_section(), timeout_seconds),
        _bounded("loki", loki_section(), timeout_seconds)
    )
    
    context = FailureContext(
        entity_type=entity_type,
        entity_id=entity_id,
        generated_at=datetime.now(UTC),
        postgres=postgres,
        prometheus=prometheus,
        logs=logs,
    )
    if context.degraded_sources:
        logger.warning(
            "failure context degraded",
            extra={
                "entity_type": entity_type.value,
                "entity_id": entity_id,
                "missing_sources": context.degraded_sources,
            },
        )
    return context
