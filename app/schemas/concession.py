from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ConcessionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: Decimal
    category: str
    size: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool = True

    model_config = {"from_attributes": True}


class ConcessionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    price: Decimal = Field(..., gt=0)
    category: str = Field(default="combo")
    size: Optional[str] = Field(None, max_length=10)
    image_url: Optional[str] = None
    is_active: bool = True


class ConcessionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0)
    category: Optional[str] = None
    size: Optional[str] = Field(None, max_length=10)
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class ConcessionOrderItem(BaseModel):
    """Sent from client to order concessions during booking."""
    concession_id: int
    quantity: int = Field(..., ge=1, le=10)


class ReservationConcessionResponse(BaseModel):
    id: int
    concession_id: int
    quantity: int
    unit_price: Decimal
    concession: Optional[ConcessionResponse] = None

    model_config = {"from_attributes": True}
