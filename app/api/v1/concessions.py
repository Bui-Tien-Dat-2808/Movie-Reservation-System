from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.concession import ConcessionCreate, ConcessionResponse, ConcessionUpdate
from app.services.concession_service import ConcessionService

router = APIRouter(prefix="/concessions", tags=["Concessions"])


@router.get("/", response_model=List[ConcessionResponse])
async def list_active_concessions(db: AsyncSession = Depends(get_db)):
    service = ConcessionService(db)
    return await service.list_concessions(active_only=True)


@router.get("/all", response_model=List[ConcessionResponse])
async def list_all_concessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = ConcessionService(db)
    return await service.list_concessions(active_only=False)


@router.post("/", response_model=ConcessionResponse, status_code=status.HTTP_201_CREATED)
async def create_concession(
    payload: ConcessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = ConcessionService(db)
    return await service.create_concession(payload)


@router.put("/{concession_id}", response_model=ConcessionResponse)
async def update_concession(
    concession_id: int,
    payload: ConcessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = ConcessionService(db)
    try:
        return await service.update_concession(concession_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
