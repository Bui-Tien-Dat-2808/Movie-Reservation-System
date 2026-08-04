"""Unit tests for Voucher validation and Reservation discount integration."""
import pytest
from fastapi import HTTPException
from app.services.voucher_service import VoucherService, PROMOTIONS_LIST


class TestVoucherService:
    """Test voucher validation and calculation logic."""

    def test_valid_percent_voucher(self):
        """Test valid percentage voucher calculation."""
        match, discount, final_amount = VoucherService.validate_and_calculate_discount("CINEVERSE10", 200000.0)
        assert match.code == "CINEVERSE10"
        assert discount == 20000.0  # 10% of 200,000 = 20,000
        assert final_amount == 180000.0

    def test_valid_fixed_voucher(self):
        """Test valid fixed amount voucher calculation."""
        match, discount, final_amount = VoucherService.validate_and_calculate_discount("HAPPYWED", 200000.0)
        assert match.code == "HAPPYWED"
        assert discount == 30000.0
        assert final_amount == 170000.0

    def test_max_discount_cap(self):
        """Test percentage voucher capped by max_discount."""
        # CINEVERSE10 has max_discount 50,000
        match, discount, final_amount = VoucherService.validate_and_calculate_discount("CINEVERSE10", 1000000.0)
        assert discount == 50000.0
        assert final_amount == 950000.0

    def test_invalid_voucher_code_raises_404(self):
        """Test invalid voucher code raises 404 HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            VoucherService.validate_and_calculate_discount("INVALIDCODE999", 200000.0)
        assert exc_info.value.status_code == 404

    def test_insufficient_min_spend_raises_400(self):
        """Test total_amount below min_spend raises 400 HTTPException."""
        # HAPPYWED min_spend is 150,000
        with pytest.raises(HTTPException) as exc_info:
            VoucherService.validate_and_calculate_discount("HAPPYWED", 100000.0)
        assert exc_info.value.status_code == 400
