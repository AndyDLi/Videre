"""
Job state and history, read from Postgres.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from videre.database.tables import Job

from ..dependencies import SessionDependency
from .pagination import Page, Pagination, pagination_parameters
from .schemas import JobDetailResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobResponse])
async def list_jobs(
    session: SessionDependency,
    pagination: Annotated[Pagination, Depends(pagination_parameters)],
    cluster_id: Annotated[str | None, Query()] = None,
    lifecycle_state: Annotated[str | None, Query()] = None,
) -> Page[JobResponse]:
    filters = []
    if cluster_id is not None:
        filters.append(Job.cluster_id == cluster_id)
    if lifecycle_state is not None:
        filters.append(Job.lifecycle_state == lifecycle_state)
    
    total = (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(*filters)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Job)
            .where(*filters)
            .order_by(Job.created_at.desc(), Job.id)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).scalars().all()
    
    return Page[JobResponse](
        items=[JobResponse.model_validate(row) for row in rows],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset
    )


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str, session: SessionDependency) -> JobDetailResponse:
    statement = select(Job).where(Job.id == job_id).options(selectinload(Job.node_assignments))
    job = (await session.execute(statement)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    
    response = JobDetailResponse.model_validate(job)
    response.assigned_node_ids = sorted(assignment.node_id for assignment in job.node_assignments)
    return response
