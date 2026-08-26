import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.review_service import ReviewService
from app.schemas.review import ReviewCreate


@pytest.mark.asyncio
async def test_get_movie_reviews_summary():
    mock_db = AsyncMock()
    mock_cache = AsyncMock()

    # Mock stats
    stats_result = MagicMock()
    stats_result.all.return_value = [(5, 4), (4, 1)]

    verified_result = MagicMock()
    verified_result.scalar_one.return_value = 3

    items_result = MagicMock()
    items_result.scalars().all.return_value = []

    mock_db.execute.side_effect = [stats_result, verified_result, items_result]

    service = ReviewService(mock_db, mock_cache)
    res = await service.get_movie_reviews(movie_id=1)

    assert res.total == 5
    assert res.summary.average_rating == 4.8  # (5*4 + 4*1) / 5 = 24/5 = 4.8
    assert res.summary.verified_reviews_count == 3
    assert res.summary.rating_distribution[5] == 4
    assert res.summary.rating_distribution[4] == 1


@pytest.mark.asyncio
async def test_admin_toggle_approve():
    mock_db = AsyncMock()
    mock_cache = AsyncMock()

    mock_review = MagicMock()
    mock_review.id = 10
    mock_review.is_approved = True

    review_res = MagicMock()
    review_res.scalar_one_or_none.return_value = mock_review

    mock_db.execute.return_value = review_res

    service = ReviewService(mock_db, mock_cache)
    result = await service.admin_toggle_approve(review_id=10, is_approved=False)

    assert result["is_approved"] is False
    assert mock_review.is_approved is False
