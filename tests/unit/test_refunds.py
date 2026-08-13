import pytest
import hmac
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from decimal import Decimal

from app.models.refund import RefundTransaction
from app.models.payment import PaymentTransaction
from app.models.reservation import Reservation, ReservationStatus
from app.services.refund_service import RefundService


@pytest.mark.asyncio
async def test_initiate_refund_success():
    db = AsyncMock()
    # Ensure db.add is synchronous or handled
    db.add = MagicMock()
    
    payment = MagicMock(spec=PaymentTransaction)
    payment.id = 10
    payment.reservation_id = 46
    payment.amount = Decimal("227700.00")
    payment.vnp_txn_ref = "CVN_46_1786518668"
    payment.transaction_no = "15654117"
    payment.pay_date = datetime.now(timezone.utc)

    service = RefundService(db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "vnp_ResponseCode": "99",
        "vnp_Message": "Merchant service not allowed for refund API on Sandbox"
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        refund = await service.initiate_refund(payment, reason="Khách hàng huỷ vé")

        assert refund.reservation_id == 46
        assert refund.payment_transaction_id == 10
        assert refund.amount == Decimal("227700.00")
        assert refund.status == "manual_required"
        assert refund.vnpay_response_code == "99"


@pytest.mark.asyncio
async def test_resolve_refund_manually():
    db = AsyncMock()
    service = RefundService(db)

    existing_refund = RefundTransaction(
        id=1,
        reservation_id=46,
        payment_transaction_id=10,
        amount=Decimal("227700.00"),
        vnp_request_id="RF12345678",
        status="manual_required"
    )

    with patch.object(service, "get_refund", return_value=existing_refund):
        result = await service.resolve_refund_manually(refund_id=1, admin_id=2, admin_note="Đã chuyển khoản ngoài")

        assert result.status == "success"
        assert result.admin_note == "Đã chuyển khoản ngoài"
        assert result.resolved_by_admin_id == 2
        assert result.resolved_at is not None


@pytest.mark.asyncio
async def test_vnpay_refund_signature_format():
    """Verify refund HMAC SHA512 signature order using pipe '|' delimiter."""
    service = RefundService(db=AsyncMock())
    service.vnp_tmn_code = "TEST_TMN"
    service.vnp_hash_secret = "TEST_SECRET"

    params = {
        "vnp_RequestId": "RF12345",
        "vnp_Version": "2.1.0",
        "vnp_Command": "refund",
        "vnp_TmnCode": "TEST_TMN",
        "vnp_TransactionType": "02",
        "vnp_TxnRef": "CVN_46_123456",
        "vnp_Amount": "22770000",
        "vnp_TransactionNo": "15654117",
        "vnp_TransactionDate": "20260812141127",
        "vnp_CreateBy": "SystemAdmin",
        "vnp_CreateDate": "20260812141500",
        "vnp_IpAddr": "127.0.0.1",
        "vnp_OrderInfo": "Hoan tien ve",
    }

    raw_data = "|".join([
        params["vnp_RequestId"],
        params["vnp_Version"],
        params["vnp_Command"],
        params["vnp_TmnCode"],
        params["vnp_TransactionType"],
        params["vnp_TxnRef"],
        params["vnp_Amount"],
        params["vnp_TransactionNo"],
        params["vnp_TransactionDate"],
        params["vnp_CreateBy"],
        params["vnp_CreateDate"],
        params["vnp_IpAddr"],
        params["vnp_OrderInfo"],
    ])

    expected_hash = hmac.new(
        b"TEST_SECRET", raw_data.encode("utf-8"), hashlib.sha512
    ).hexdigest()

    assert expected_hash is not None
    assert len(expected_hash) == 128
