"""Bounded service metrics."""

from time import perf_counter
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)


class DatabaseMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.query = Histogram(
            "videre_database_query_seconds", "Database cursor execution time, excluding pool acquisition.",
            ["operation", "outcome"], buckets=BUCKETS, registry=registry,
        )
        self.acquisition = Histogram(
            "videre_database_acquisition_seconds",
            "ORM connection acquisition time, including connection setup/checks and existing connection lookup.",
            ["outcome"], buckets=BUCKETS, registry=registry,
        )
        self.checked_out = Gauge(
            "videre_database_connections_checked_out", "Connections currently held by the backend.", registry=registry,
        )


DATABASE = DatabaseMetrics()
AI_CACHE_READS = Counter("videre_ai_cache_reads_total", "AI response cache lookup results.", ["result"])
AI_CACHE_GET = Histogram(
    "videre_ai_cache_get_seconds", "AI response cache Redis GET time.", ["outcome"], buckets=BUCKETS,
)


def measured_session_factory(
    engine: AsyncEngine, metrics: DatabaseMetrics = DATABASE,
) -> async_sessionmaker[AsyncSession]:
    held: set[int] = set()

    def checkout(connection: Any, record: Any, proxy: Any) -> None:
        held.add(id(record))
        metrics.checked_out.set(len(held))

    def checkin(connection: Any, record: Any) -> None:
        held.discard(id(record))
        metrics.checked_out.set(len(held))

    def before_cursor(connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        context._videre_query_started = perf_counter()
        verb = statement.lstrip().split(None, 1)[0].lower() if statement.strip() else "other"
        context._videre_operation = verb if verb in {"select", "insert", "update", "delete"} else "other"

    def observe(context: Any, outcome: str) -> None:
        started = getattr(context, "_videre_query_started", None)
        if started is not None:
            metrics.query.labels(context._videre_operation, outcome).observe(perf_counter() - started)
            context._videre_query_started = None

    def after_cursor(connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        observe(context, "success")

    def failed_cursor(context: Any) -> None:
        observe(context.execution_context, "error")

    class MeasuredSession(Session):
        pass

    def acquire(state: Any) -> None:
        started = perf_counter()
        outcome = "error"
        try:
            state.session.connection(bind_arguments=dict(state.bind_arguments))
            outcome = "success"
        finally:
            metrics.acquisition.labels(outcome).observe(perf_counter() - started)

    event.listen(engine.sync_engine, "checkout", checkout)
    event.listen(engine.sync_engine, "checkin", checkin)
    event.listen(engine.sync_engine, "detach", checkin)
    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor)
    event.listen(engine.sync_engine, "handle_error", failed_cursor)
    event.listen(MeasuredSession, "do_orm_execute", acquire)
    return async_sessionmaker(engine, expire_on_commit=False, sync_session_class=MeasuredSession)
