"""
Shared pagination for list endpoints.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAXIMUM_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class Page[ItemT](BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    items: list[ItemT]
    total: int
    limit: int
    offset: int


def pagination_parameters(
    limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
