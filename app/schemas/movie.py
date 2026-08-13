from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl

from app.models.movie import MovieStatus
from app.schemas.genre import GenreResponse


class MovieBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    poster_url: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=0, le=600)
    release_date: Optional[date] = None
    language: Optional[str] = Field(None, max_length=100)
    rating: Optional[str] = Field(None, max_length=10)
    director: Optional[str] = Field(None, max_length=255)
    popularity: Optional[float] = None
    status: MovieStatus = MovieStatus.NOW_SHOWING


class MovieCreate(MovieBase):
    genre_ids: List[int] = Field(default_factory=list)
    tmdb_id: Optional[int] = None


class MovieUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    poster_url: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=0, le=600)
    release_date: Optional[date] = None
    language: Optional[str] = None
    rating: Optional[str] = None
    director: Optional[str] = None
    popularity: Optional[float] = None
    status: Optional[MovieStatus] = None
    genre_ids: Optional[List[int]] = None


class MovieResponse(MovieBase):
    id: int
    tmdb_id: Optional[int]
    is_active: bool
    genres: List[GenreResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MovieListResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    poster_url: Optional[str]
    duration_minutes: Optional[int]
    release_date: Optional[date]
    rating: Optional[str]
    director: Optional[str]
    popularity: Optional[float] = None
    status: MovieStatus
    genres: List[GenreResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}
