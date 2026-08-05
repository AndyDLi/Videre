"""
Aged history is pruned to a 3-day window, run as a background task.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Delete, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videre.database.tables import FailureEntityTable, FailureRecord, Job, SchedulerEventRecord

logger = logging.getLogger("videre.backend.retention")

RETENTION_WINDOW = timedelta(days=3)
PRUNE_INTERVAL_SECONDS = 3600.0


async def _delete_rows(session: AsyncSession, statement: Delete) -> int:
    result = cast(CursorResult[Any], await session.execute(statement))
    return result.rowcount


async def prune_once(session: AsyncSession, cutoff: datetime) -> dict[str, int]:
    return {
        "failure_records": await _delete_rows(
            session,
            delete(FailureRecord).where(
                FailureRecord.detected_at < cutoff,
                or_(
                    FailureRecord.resolved_at.is_not(None),
                    FailureRecord.entity_type == FailureEntityTable.JOB.value,    # node or GPU failures survive
                ),
            ),
        ),
        "jobs": await _delete_rows(session, delete(Job).where(Job.updated_at < cutoff)),
        "scheduler_events": await _delete_rows(
            session, delete(SchedulerEventRecord).where(SchedulerEventRecord.timestamp < cutoff)
        ),
    }


async def run_retention_pruning(
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: float = PRUNE_INTERVAL_SECONDS,
) -> None:
    while True:
        try:
            async with session_factory() as session, session.begin():
                deleted = await prune_once(session, datetime.now(UTC) - RETENTION_WINDOW)
            if any(deleted.values()):
                logger.info("pruned aged history", extra=deleted)
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("retention pruning stopped")
            raise
        except Exception as error:
            logger.error("retention prune failed", extra={"error": str(error)})
            await asyncio.sleep(interval_seconds)
