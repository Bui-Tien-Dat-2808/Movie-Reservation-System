from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ConcessionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    price: Decimal = Field(..., gt=0)
    category: str = Field("combo", max_length=50)
    size: Optional[str] = Field(None, max_length=10)
    image_url: Optional[str] = None
    is_active: bool = True


class ConcessionCreate(ConcessionBase):
    pass


class ConcessionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0)
    category: Optional[str] = None
    size: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class ConcessionResponse(ConcessionBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ConcessionOrderItem(BaseModel):
    concession_id: int
    quantity: int = Field(..., gt=0)


class ReservationConcessionResponse(BaseModel):
    concession_id: int
    quantity: int
    unit_price: Decimal
    concession_name: Optional[str] = None

    model_config = {"from_attributes": True}
