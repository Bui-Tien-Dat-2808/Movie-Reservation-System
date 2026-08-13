from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=50)
    date_of_birth: Optional[str] = Field(None, max_length=50)
    gender: Optional[str] = Field(None, max_length=20)
    region: Optional[str] = Field(None, max_length=100)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    turnstile_token: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    region: Optional[str] = None


class UserResponse(UserBase):
    id: int
    role: UserRole
    is_active: bool
    must_change_password: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    id: int
    email: str
    full_name: str
    phone_number: Optional[str] = None
    role: UserRole
    is_active: bool
    loyalty_points: int = 0
    loyalty_tier: str = "bronze"
    created_at: datetime

    model_config = {"from_attributes": True}
