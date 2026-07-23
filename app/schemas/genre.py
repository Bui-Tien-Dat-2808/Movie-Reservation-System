from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GenreBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class GenreCreate(GenreBase):
    pass


class GenreUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class GenreResponse(GenreBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
