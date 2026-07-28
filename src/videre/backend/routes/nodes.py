"""
Node and GPU current state.
Read from Postgres since it is cheap to query with indexes and parameters.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from videre.database.tables import Node

from ..dependencies import SessionDependency
from .pagination import Page, Pagination, pagination_parameters
from .schemas import NodeDetailResponse, NodeResponse

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=Page[NodeResponse])
async def list_nodes(
    session: SessionDependency,
    pagination: Annotated[Pagination, Depends(pagination_parameters)],
    cluster_id: Annotated[str | None, Query()] = None,
    health_state: Annotated[str | None, Query()] = None,
) -> Page[NodeResponse]:
    filters = []
    if cluster_id is not None:
        filters.append(Node.cluster_id == cluster_id)
    if health_state is not None:
        filters.append(Node.health_state == health_state)
    
    total = (
        await session.execute(
            select(func.count())
            .select_from(Node)
            .where(*filters)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Node)
            .where(*filters)
            .order_by(Node.id)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).scalars().all()
    
    return Page[NodeResponse](
        items=[NodeResponse.model_validate(row) for row in rows],
        total=int(total),
        limit=pagination.limit,
        offset=pagination.offset
    )


@router.get("/{node_id}", response_model=NodeDetailResponse)
async def get_node(node_id: str, session: SessionDependency) -> NodeDetailResponse:
    statement = select(Node).where(Node.id == node_id).options(selectinload(Node.gpus))    # avoids n+1 query problem
    node = (await session.execute(statement)).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return NodeDetailResponse.model_validate(node)
