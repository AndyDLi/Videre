"""
The cheap lookup done before the response cache is consulted to
determine if the cached response is still valid.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from videre.database.tables import FailureEntityTable, FailureRecord, Gpu, Job, Node

_ENTITY_COLUMNS: dict[FailureEntityTable, tuple[InstrumentedAttribute[str], InstrumentedAttribute[str]]] = {
    FailureEntityTable.NODE: (Node.id, Node.health_state),
    FailureEntityTable.GPU: (Gpu.id, Gpu.health_state),
    FailureEntityTable.JOB: (Job.id, Job.lifecycle_state),
}


class EntityFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    
    entity_type: FailureEntityTable
    entity_id: str
    health_state: str
    unresolved_failure_ids: tuple[str, ...]
    
    @property
    def cache_fingerprint(self) -> str:
        return ":".join(
            (
                self.entity_type.value,
                self.entity_id,
                self.health_state,
                ",".join(self.unresolved_failure_ids)
            )
        )


async def load_fingerprint(
    session: AsyncSession,
    entity_type: FailureEntityTable,
    entity_id: str
) -> EntityFingerprint | None:
    id_column, state_column = _ENTITY_COLUMNS[entity_type]
    statement = (
        select(state_column, func.array_agg(FailureRecord.id))
        .outerjoin(
            FailureRecord,
            and_(
                FailureRecord.entity_type == entity_type.value,
                FailureRecord.entity_id == id_column,
                FailureRecord.resolved_at.is_(None)
            )
        )
        .where(id_column == entity_id)
        .group_by(id_column)
    )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    
    health_state, aggregated_ids = row
    failure_ids = tuple(sorted(value for value in aggregated_ids if value is not None))
    
    return EntityFingerprint(
        entity_type=entity_type,
        entity_id=entity_id,
        health_state=health_state,
        unresolved_failure_ids=failure_ids
    )
