from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import structlog
from app.core.exceptions import NotFoundException

logger = structlog.get_logger()
from app.models.movie import Movie
from app.models.reservation import Reservation, ReservationStatus
from app.models.review import Review
from app.models.showtime import Showtime
from app.schemas.review import (
    MovieReviewSummary,
    MovieReviewsListResponse,
    ReviewCreate,
    ReviewResponse,
    ReviewUpdate,
    ReviewUser,
)
from app.services.cache_service import CacheService


class ReviewService:
    def __init__(self, db: AsyncSession, cache: Optional[CacheService] = None):
        self.db = db
        self.cache = cache or CacheService()

    async def get_movie_reviews(
        self, movie_id: int, page: int = 1, page_size: int = 20
    ) -> MovieReviewsListResponse:
        """Fetch approved reviews and rating summary for a movie."""
        # 1. Fetch rating stats (approved only)
        stats_res = await self.db.execute(
            select(
                Review.rating,
                func.count(Review.id)
            ).where(
                Review.movie_id == movie_id,
                Review.is_approved == True
            ).group_by(Review.rating)
        )
        rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        total_reviews = 0
        total_score = 0

        for r_val, count in stats_res.all():
            if r_val in rating_counts:
                rating_counts[r_val] = count
            total_reviews += count
            total_score += r_val * count

        verified_res = await self.db.execute(
            select(func.count(Review.id)).where(
                Review.movie_id == movie_id,
                Review.is_approved == True,
                Review.is_verified_booking == True
            )
        )
        verified_count = verified_res.scalar_one() or 0

        avg_rating = round(total_score / total_reviews, 1) if total_reviews > 0 else 0.0

        summary = MovieReviewSummary(
            average_rating=avg_rating,
            total_reviews=total_reviews,
            rating_distribution=rating_counts,
            verified_reviews_count=verified_count,
        )

        # 2. Fetch paginated reviews
        offset = (page - 1) * page_size
        reviews_query = (
            select(Review)
            .where(Review.movie_id == movie_id, Review.is_approved == True)
            .options(selectinload(Review.user))
            .order_by(Review.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items_res = await self.db.execute(reviews_query)
        review_items = items_res.scalars().all()

        items = []
        for r in review_items:
            u_info = None
            if r.user:
                u_info = ReviewUser(
                    id=r.user.id,
                    full_name=r.user.full_name or r.user.email.split("@")[0],
                    email=r.user.email,
                    avatar_url=getattr(r.user, "avatar_url", None)
                )
            items.append(
                ReviewResponse(
                    id=r.id,
                    movie_id=r.movie_id,
                    user_id=r.user_id,
                    rating=r.rating,
                    comment=r.comment,
                    is_verified_booking=r.is_verified_booking,
                    is_approved=r.is_approved,
                    user=u_info,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
            )

        return MovieReviewsListResponse(
            items=items,
            total=total_reviews,
            summary=summary,
        )

    async def get_user_review_for_movie(
        self, user_id: int, movie_id: int
    ) -> Optional[ReviewResponse]:
        """Fetch user own review for a movie."""
        res = await self.db.execute(
            select(Review)
            .where(Review.user_id == user_id, Review.movie_id == movie_id)
            .options(selectinload(Review.user))
        )
        r = res.scalar_one_or_none()
        if not r:
            return None

        u_info = None
        if r.user:
            u_info = ReviewUser(
                id=r.user.id,
                full_name=r.user.full_name or r.user.email.split("@")[0],
                email=r.user.email,
                avatar_url=getattr(r.user, "avatar_url", None)
            )

        return ReviewResponse(
            id=r.id,
            movie_id=r.movie_id,
            user_id=r.user_id,
            rating=r.rating,
            comment=r.comment,
            is_verified_booking=r.is_verified_booking,
            is_approved=r.is_approved,
            user=u_info,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    async def create_or_update_review(
        self, user_id: int, movie_id: int, data: ReviewCreate
    ) -> ReviewResponse:
        """Create or update a review for a movie."""
        # 1. Verify movie exists
        movie_res = await self.db.execute(select(Movie).where(Movie.id == movie_id))
        if not movie_res.scalar_one_or_none():
            raise NotFoundException("Movie", movie_id)

        # 2. Check if user has confirmed booking for this movie
        booking_check = await self.db.execute(
            select(Reservation.id)
            .join(Showtime, Reservation.showtime_id == Showtime.id)
            .where(
                Reservation.user_id == user_id,
                Showtime.movie_id == movie_id,
                Reservation.status == ReservationStatus.CONFIRMED,
            )
            .limit(1)
        )
        is_verified = booking_check.scalar_one_or_none() is not None

        # 3. Check if existing review exists
        existing_res = await self.db.execute(
            select(Review).where(Review.user_id == user_id, Review.movie_id == movie_id)
        )
        review = existing_res.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if review:
            review.rating = data.rating
            review.comment = data.comment
            review.is_verified_booking = is_verified or review.is_verified_booking
            review.updated_at = now
            self.db.add(review)
        else:
            review = Review(
                user_id=user_id,
                movie_id=movie_id,
                rating=data.rating,
                comment=data.comment,
                is_verified_booking=is_verified,
                is_approved=True,
                created_at=now,
                updated_at=now,
            )
        try:
            await self.db.commit()
            await self.db.refresh(review)
        except Exception:
            await self.db.rollback()
            existing_res = await self.db.execute(
                select(Review).where(Review.user_id == user_id, Review.movie_id == movie_id)
            )
            review = existing_res.scalar_one_or_none()
            if review:
                review.rating = data.rating
                review.comment = data.comment
                review.is_verified_booking = is_verified or review.is_verified_booking
                review.updated_at = now
                self.db.add(review)
                await self.db.commit()
                await self.db.refresh(review)

        return await self.get_user_review_for_movie(user_id, movie_id)

    async def delete_review(self, user_id: int, movie_id: int) -> bool:
        """Delete user review."""
        res = await self.db.execute(
            select(Review).where(Review.user_id == user_id, Review.movie_id == movie_id)
        )
        review = res.scalar_one_or_none()
        if not review:
            raise NotFoundException("Review", f"movie={movie_id}")

        await self.db.delete(review)
        await self.db.commit()
        return True

    # ─── Admin Moderation Methods ─────────────────────────────────────────────

    async def admin_get_reviews(
        self,
        movie_id: Optional[int] = None,
        is_approved: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[dict], int]:
        """Admin: list all reviews with filter and pagination."""
        query = select(Review)
        if movie_id is not None:
            query = query.where(Review.movie_id == movie_id)
        if is_approved is not None:
            query = query.where(Review.is_approved == is_approved)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        offset = (page - 1) * page_size
        query = (
            query.options(selectinload(Review.user), selectinload(Review.movie))
            .order_by(Review.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        res = await self.db.execute(query)
        reviews = res.scalars().all()

        results = []
        for r in reviews:
            results.append({
                "id": r.id,
                "movie_id": r.movie_id,
                "movie_title": r.movie.title if r.movie else f"Phim #{r.movie_id}",
                "user_id": r.user_id,
                "user_name": r.user.full_name or (r.user.email.split("@")[0] if r.user else "User"),
                "user_email": r.user.email if r.user else "",
                "rating": r.rating,
                "comment": r.comment,
                "is_verified_booking": r.is_verified_booking,
                "is_approved": r.is_approved,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            })

        return results, total

    async def admin_toggle_approve(self, review_id: int, is_approved: bool) -> dict:
        """Admin: approve or hide a review."""
        res = await self.db.execute(
            select(Review).where(Review.id == review_id).options(selectinload(Review.movie))
        )
        review = res.scalar_one_or_none()
        if not review:
            raise NotFoundException("Review", review_id)

        review.is_approved = is_approved
        review.updated_at = datetime.now(timezone.utc)
        self.db.add(review)
        await self.db.commit()
        return {
            "id": review.id,
            "is_approved": review.is_approved,
            "message": "Đã duyệt bình luận" if is_approved else "Đã ẩn bình luận",
        }

    async def admin_delete_review(self, review_id: int) -> bool:
        """Admin: permanently delete a review."""
        res = await self.db.execute(select(Review).where(Review.id == review_id))
        review = res.scalar_one_or_none()
        if not review:
            raise NotFoundException("Review", review_id)

        await self.db.delete(review)
        await self.db.commit()
        return True
