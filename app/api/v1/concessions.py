from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.concession import ConcessionCreate, ConcessionResponse, ConcessionUpdate
from app.services.concession_service import ConcessionService

router = APIRouter(prefix="/concessions", tags=["Concessions"])


@router.get("/", response_model=List[ConcessionResponse])
async def list_active_concessions(
    db: AsyncSession = Depends(get_db),
):
    """List all active popcorn & drink combos for booking selection."""
    service = ConcessionService(db)
    return await service.get_all_active()


@router.get("/all", response_model=List[ConcessionResponse])
async def list_all_concessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin: list all concession items (including inactive)."""
    service = ConcessionService(db)
    return await service.get_all()


@router.post("/", response_model=ConcessionResponse, status_code=status.HTTP_201_CREATED)
async def create_concession(
    data: ConcessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin: create a new concession item."""
    service = ConcessionService(db)
    return await service.create(data)


@router.put("/{concession_id}", response_model=ConcessionResponse)
async def update_concession(
    concession_id: int,
    data: ConcessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin: update an existing concession item."""
    service = ConcessionService(db)
    result = await service.update(concession_id, data)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Concession {concession_id} not found",
        )
    return result
