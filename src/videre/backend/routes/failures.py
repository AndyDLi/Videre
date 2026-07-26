"""
Failure records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from videre.database.tables import FailureRecord

from ..dependencies import SessionDependency
from .pagination import Page, Pagination, pagination_parameters
from .schemas import FailureResponse

router = APIRouter(prefix="/failures", tags=["failures"])


@router.get("", response_model=Page[FailureResponse])
async def list_failures(
    session: SessionDependency,
    pagination: Annotated[Pagination, Depends(pagination_parameters)],
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    resolved: Annotated[bool | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
) -> Page[FailureResponse]:
    filters = []
    if entity_type is not None:
        filters.append(FailureRecord.entity_type == entity_type)
    if entity_id is not None:
        filters.append(FailureRecord.entity_id == entity_id)
    if resolved is True:
        filters.append(FailureRecord.resolved_at.is_not(None))
    elif resolved is False:
        filters.append(FailureRecord.resolved_at.is_(None))
    if since is not None:
        filters.append(FailureRecord.detected_at >= since)
        
    total = (
        await session.execute(
            select(func.count())
            .select_from(FailureRecord)
            .where(*filters)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(FailureRecord)
            .where(*filters)
            .order_by(FailureRecord.detected_at.desc(), FailureRecord.id)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).scalars().all()
    
    return Page[FailureResponse](
        items=[FailureResponse.model_validate(row) for row in rows],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset
    )
