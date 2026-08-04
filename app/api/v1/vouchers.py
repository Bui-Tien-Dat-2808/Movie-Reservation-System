from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_user_optional, require_admin
from app.models.user import User
from app.models.voucher import Voucher
from app.schemas.voucher import VoucherCreate, VoucherResponse, VoucherUpdate
from app.services.voucher_service import VoucherService

router = APIRouter(prefix="/vouchers", tags=["Vouchers & Promotions"])


class ApplyVoucherRequest(BaseModel):
    code: str
    total_amount: float


class ApplyVoucherResponse(BaseModel):
    valid: bool
    code: str
    discount_amount: float
    final_amount: float
    message: str


@router.get("/", response_model=List[VoucherResponse], summary="Get active promotions & vouchers")
async def list_vouchers(db: AsyncSession = Depends(get_db)):
    """Public: List all active promotional offers and voucher codes."""
    res = await db.execute(select(Voucher).where(Voucher.is_active == True))
    return list(res.scalars().all())


@router.get("/admin/all", response_model=List[VoucherResponse], summary="Admin: List all vouchers including inactive")
async def list_all_vouchers_admin(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: List all vouchers in database."""
    res = await db.execute(select(Voucher).order_by(Voucher.id.desc()))
    return list(res.scalars().all())


@router.post("/apply", response_model=ApplyVoucherResponse, summary="Apply voucher code")
async def apply_voucher(
    req: ApplyVoucherRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Validate and calculate discount for a voucher code."""
    service = VoucherService(db)
    user_id = current_user.id if current_user else None

    match, discount, final_amount = await service.validate_and_calculate_discount(
        req.code, req.total_amount, user_id=user_id
    )

    return ApplyVoucherResponse(
        valid=True,
        code=match.code,
        discount_amount=discount,
        final_amount=final_amount,
        message=f"Đã áp dụng thành công mã {match.code}! Bạn được giảm {discount:,.0f} VNĐ.",
    )


@router.post("/", response_model=VoucherResponse, status_code=status.HTTP_201_CREATED, summary="Admin: Create voucher")
async def create_voucher(
    data: VoucherCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Create a new voucher."""
    code_upper = data.code.strip().upper()
    existing = await db.execute(select(Voucher).where(Voucher.code == code_upper))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mã voucher '{code_upper}' đã tồn tại trên hệ thống.",
        )

    voucher_data = data.model_dump()
    voucher_data["code"] = code_upper
    voucher = Voucher(**voucher_data)
    db.add(voucher)
    await db.commit()
    await db.refresh(voucher)
    return voucher


@router.put("/{voucher_id}", response_model=VoucherResponse, summary="Admin: Update voucher")
async def update_voucher(
    voucher_id: int,
    data: VoucherUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Update an existing voucher."""
    res = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = res.scalar_one_or_none()
    if not voucher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy voucher ID {voucher_id}.",
        )

    update_dict = data.model_dump(exclude_unset=True)
    if "code" in update_dict:
        update_dict["code"] = update_dict["code"].strip().upper()

    for k, v in update_dict.items():
        setattr(voucher, k, v)

    await db.commit()
    await db.refresh(voucher)
    return voucher


@router.delete("/{voucher_id}", summary="Admin: Delete voucher")
async def delete_voucher(
    voucher_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Delete a voucher by ID."""
    res = await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    voucher = res.scalar_one_or_none()
    if not voucher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy voucher ID {voucher_id}.",
        )

    await db.delete(voucher)
    await db.commit()
    return {"message": f"Đã xóa voucher {voucher.code} thành công."}
