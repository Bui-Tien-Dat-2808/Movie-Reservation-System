"""Unit tests for Voucher validation and Reservation discount integration with DB rules."""
from datetime import date, timedelta
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.models.reservation import ReservationStatus
from app.models.voucher import Voucher, VoucherDiscountType, VoucherRedemption
from app.services.voucher_service import VoucherService


class TestVoucherService:
    """Test voucher validation and calculation logic with DB rules."""

    @pytest.mark.asyncio
    async def test_valid_percent_voucher(self):
        """Test valid percentage voucher calculation."""
        db_mock = AsyncMock()
        voucher = Voucher(
            id=1,
            code="WELCOME10",
            discount_type=VoucherDiscountType.PERCENT,
            discount_value=10.0,
            min_spend=100000.0,
            max_discount=50000.0,
            expiry_date=date.today() + timedelta(days=30),
            is_active=True,
        )
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = voucher
        db_mock.execute.return_value = res_mock

        service = VoucherService(db_mock)
        match, discount, final_amount = await service.validate_and_calculate_discount("WELCOME10", 200000.0)

        assert match.code == "WELCOME10"
        assert discount == 20000.0
        assert final_amount == 180000.0

    @pytest.mark.asyncio
    async def test_expired_voucher_raises_400(self):
        """Test expired voucher raises 400 HTTPException."""
        db_mock = AsyncMock()
        expired_voucher = Voucher(
            id=2,
            code="EXPIRED50",
            discount_type=VoucherDiscountType.PERCENT,
            discount_value=50.0,
            min_spend=0.0,
            expiry_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = expired_voucher
        db_mock.execute.return_value = res_mock

        service = VoucherService(db_mock)
        with pytest.raises(HTTPException) as exc_info:
            await service.validate_and_calculate_discount("EXPIRED50", 100000.0)
        assert exc_info.value.status_code == 400
        assert "hết hạn sử dụng" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_weekday_restriction_raises_400(self):
        """Test voucher valid only on specific weekdays raises 400 on other days."""
        db_mock = AsyncMock()
        # Set valid_weekdays to a day different than today
        wrong_day = (date.today().weekday() + 1) % 7
        wed_voucher = Voucher(
            id=3,
            code="HAPPYWED",
            discount_type=VoucherDiscountType.FIXED,
            discount_value=30000.0,
            min_spend=100000.0,
            expiry_date=date.today() + timedelta(days=30),
            valid_weekdays=[wrong_day],
            is_active=True,
        )
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = wed_voucher
        db_mock.execute.return_value = res_mock

        service = VoucherService(db_mock)
        with pytest.raises(HTTPException) as exc_info:
            await service.validate_and_calculate_discount("HAPPYWED", 200000.0)
        assert exc_info.value.status_code == 400
        assert "không áp dụng" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_first_booking_only_raises_400(self):
        """Test is_first_booking_only voucher raises 400 if user has prior confirmed reservations."""
        db_mock = AsyncMock()
        first_voucher = Voucher(
            id=4,
            code="CINEVERSE10",
            discount_type=VoucherDiscountType.PERCENT,
            discount_value=10.0,
            min_spend=0.0,
            is_first_booking_only=True,
            is_active=True,
        )
        v_res = MagicMock()
        v_res.scalar_one_or_none.return_value = first_voucher

        count_res = MagicMock()
        count_res.scalar_one.return_value = 1  # 1 existing confirmed booking

        db_mock.execute.side_effect = [v_res, count_res]

        service = VoucherService(db_mock)
        with pytest.raises(HTTPException) as exc_info:
            await service.validate_and_calculate_discount("CINEVERSE10", 100000.0, user_id=10)
        assert exc_info.value.status_code == 400
        assert "đầu tiên" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_max_uses_per_user_raises_400(self):
        """Test max_uses_per_user reached raises 400."""
        db_mock = AsyncMock()
        limited_voucher = Voucher(
            id=5,
            code="LIMITED1",
            discount_type=VoucherDiscountType.FIXED,
            discount_value=10000.0,
            min_spend=0.0,
            max_uses_per_user=1,
            is_active=True,
        )
        v_res = MagicMock()
        v_res.scalar_one_or_none.return_value = limited_voucher

        uses_res = MagicMock()
        uses_res.scalar_one.return_value = 1  # Already used 1 time

        db_mock.execute.side_effect = [v_res, uses_res]

        service = VoucherService(db_mock)
        with pytest.raises(HTTPException) as exc_info:
            await service.validate_and_calculate_discount("LIMITED1", 100000.0, user_id=10)
        assert exc_info.value.status_code == 400
        assert "tối đa" in exc_info.value.detail
