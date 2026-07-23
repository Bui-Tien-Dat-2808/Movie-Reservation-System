import math
from typing import TypeVar

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import PaginationMeta, PaginatedResponse

T = TypeVar("T")


class PaginationParams:
    """Common pagination query parameters."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number"),
        page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def build_pagination_meta(
    total: int, page: int, page_size: int
) -> PaginationMeta:
    """Build pagination metadata."""
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def paginate(items: list, total: int, page: int, page_size: int) -> PaginatedResponse:
    """Build a paginated response."""
    return PaginatedResponse(
        items=items,
        meta=build_pagination_meta(total, page, page_size),
    )
