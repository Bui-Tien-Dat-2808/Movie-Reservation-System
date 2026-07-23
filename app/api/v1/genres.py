from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.genre import Genre
from app.schemas.common import PaginatedResponse
from app.schemas.genre import GenreCreate, GenreResponse, GenreUpdate
from app.utils.pagination import PaginationParams, paginate

router = APIRouter(prefix="/genres", tags=["Genres"])
logger = structlog.get_logger()


@router.get("/", response_model=List[GenreResponse], summary="List all genres")
async def list_genres(db: AsyncSession = Depends(get_db)):
    """Get all genres (cached)."""
    result = await db.execute(select(Genre).order_by(Genre.name))
    return result.scalars().all()


@router.get("/{genre_id}", response_model=GenreResponse, summary="Get genre by ID")
async def get_genre(genre_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Genre).where(Genre.id == genre_id))
    genre = result.scalar_one_or_none()
    if not genre:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Genre", genre_id)
    return genre


@router.post(
    "/",
    response_model=GenreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create genre (Admin)",
)
async def create_genre(
    data: GenreCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin: create a new genre."""
    existing = await db.execute(select(Genre).where(Genre.name == data.name))
    if existing.scalar_one_or_none():
        from app.core.exceptions import ConflictException
        raise ConflictException(f"Genre '{data.name}' already exists")

    genre = Genre(name=data.name, description=data.description)
    db.add(genre)
    await db.flush()
    await db.refresh(genre)
    return genre


@router.put("/{genre_id}", response_model=GenreResponse, summary="Update genre (Admin)")
async def update_genre(
    genre_id: int,
    data: GenreUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin: update a genre."""
    result = await db.execute(select(Genre).where(Genre.id == genre_id))
    genre = result.scalar_one_or_none()
    if not genre:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Genre", genre_id)

    if data.name is not None:
        genre.name = data.name
    if data.description is not None:
        genre.description = data.description

    await db.flush()
    await db.refresh(genre)
    return genre


@router.delete(
    "/{genre_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete genre (Admin)",
)
async def delete_genre(
    genre_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin: delete a genre."""
    result = await db.execute(select(Genre).where(Genre.id == genre_id))
    genre = result.scalar_one_or_none()
    if not genre:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Genre", genre_id)

    await db.delete(genre)
    await db.flush()
