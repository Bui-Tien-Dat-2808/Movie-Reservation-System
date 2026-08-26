from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.dependencies import (
    get_current_active_user,
    get_review_service,
    require_admin,
)
from app.models.user import User
from app.schemas.review import (
    MovieReviewsListResponse,
    ReviewCreate,
    ReviewResponse,
    ReviewUpdate,
)
from app.services.review_service import ReviewService

router = APIRouter()


# ─── Public & User Endpoints ──────────────────────────────────────────────────

@router.get(
    "/movies/{movie_id}/reviews",
    response_model=MovieReviewsListResponse,
    summary="Get approved reviews and rating summary for a movie",
)
async def get_movie_reviews(
    movie_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: ReviewService = Depends(get_review_service),
):
    """Fetch all approved reviews and rating breakdown for a movie."""
    return await service.get_movie_reviews(movie_id, page=page, page_size=page_size)


@router.get(
    "/movies/{movie_id}/reviews/my-review",
    response_model=Optional[ReviewResponse],
    summary="Get current logged in user's review for a movie",
)
async def get_my_review(
    movie_id: int,
    current_user: User = Depends(get_current_active_user),
    service: ReviewService = Depends(get_review_service),
):
    """Get the current user's review for this movie if exists."""
    return await service.get_user_review_for_movie(current_user.id, movie_id)


@router.post(
    "/movies/{movie_id}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit or update a review for a movie",
)
async def submit_review(
    movie_id: int,
    data: ReviewCreate,
    current_user: User = Depends(get_current_active_user),
    service: ReviewService = Depends(get_review_service),
):
    """Submit rating (1-5 stars) and comment. Automatically verifies if user booked this movie."""
    return await service.create_or_update_review(current_user.id, movie_id, data)


@router.delete(
    "/movies/{movie_id}/reviews/my-review",
    summary="Delete current user's review for a movie",
)
async def delete_my_review(
    movie_id: int,
    current_user: User = Depends(get_current_active_user),
    service: ReviewService = Depends(get_review_service),
):
    """Delete own review."""
    await service.delete_review(current_user.id, movie_id)
    return {"message": "Đã xóa đánh giá của bạn thành công"}


# ─── Admin Endpoints ──────────────────────────────────────────────────────────

class ToggleApproveRequest(BaseModel):
    is_approved: bool


@router.get(
    "/reviews/admin",
    summary="Admin: List all reviews with filters",
)
async def admin_list_reviews(
    movie_id: Optional[int] = Query(None, description="Filter by movie ID"),
    is_approved: Optional[bool] = Query(None, description="Filter by approved status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    service: ReviewService = Depends(get_review_service),
):
    """Admin: Search and paginate all user reviews across all movies."""
    items, total = await service.admin_get_reviews(
        movie_id=movie_id,
        is_approved=is_approved,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.patch(
    "/reviews/admin/{review_id}/approve",
    summary="Admin: Approve or hide a review",
)
async def admin_toggle_approve(
    review_id: int,
    body: ToggleApproveRequest,
    current_user: User = Depends(require_admin),
    service: ReviewService = Depends(get_review_service),
):
    """Admin: toggle whether a review is visible publicly."""
    return await service.admin_toggle_approve(review_id, body.is_approved)


@router.delete(
    "/reviews/admin/{review_id}",
    summary="Admin: Permanently delete a review",
)
async def admin_delete_review(
    review_id: int,
    current_user: User = Depends(require_admin),
    service: ReviewService = Depends(get_review_service),
):
    """Admin: permanently delete a review."""
    await service.admin_delete_review(review_id)
    return {"message": "Đã xóa đánh giá thành công"}
