from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ReviewUser(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: str
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class ReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Điểm đánh giá từ 1 đến 5 sao")
    comment: Optional[str] = Field(None, max_length=2000, description="Bình luận cảm nhận về bộ phim")


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5, description="Điểm đánh giá từ 1 đến 5 sao")
    comment: Optional[str] = Field(None, max_length=2000, description="Bình luận cảm nhận về bộ phim")


class ReviewResponse(BaseModel):
    id: int
    movie_id: int
    user_id: int
    rating: int
    comment: Optional[str] = None
    is_verified_booking: bool = False
    is_approved: bool = True
    user: Optional[ReviewUser] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MovieReviewSummary(BaseModel):
    average_rating: float = Field(0.0, description="Điểm trung bình thang 5 sao (ví dụ: 4.5 ⭐)")
    total_reviews: int = Field(0, description="Tổng số lượt đánh giá đã duyệt")
    rating_distribution: Dict[int, int] = Field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
    verified_reviews_count: int = 0


class MovieReviewsListResponse(BaseModel):
    items: List[ReviewResponse]
    total: int
    summary: MovieReviewSummary
