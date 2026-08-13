import pytest
import hmac
import hashlib
import urllib.parse
from decimal import Decimal

from app.services.vnpay_service import VNPayService


def test_vnpay_create_payment_url():
    service = VNPayService()
    service.vnp_tmn_code = "S6967RVA"
    service.vnp_hash_secret = "NTDXCYCSAOPNANKALKQZICSVHTRLIKUX"

    url = service.create_payment_url(
        vnp_txn_ref="CVN_46_1786518668",
        amount=Decimal("227700.00"),
        order_info="Thanh toan ve CineVerse CVN-9ISIES",
        client_ip="127.0.0.1",
        return_url="http://localhost:8000/api/v1/payments/vnpay-return"
    )

    assert "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html" in url
    assert "vnp_Amount=22770000" in url
    assert "vnp_TxnRef=CVN_46_1786518668" in url
    assert "vnp_SecureHash=" in url


def test_vnpay_verify_response_valid():
    service = VNPayService()
    service.vnp_hash_secret = "NTDXCYCSAOPNANKALKQZICSVHTRLIKUX"

    params = {
        "vnp_Amount": "22770000",
        "vnp_BankCode": "NCB",
        "vnp_CardType": "ATM",
        "vnp_OrderInfo": "Thanh toan ve CineVerse",
        "vnp_PayDate": "20260812141127",
        "vnp_ResponseCode": "00",
        "vnp_TmnCode": "S6967RVA",
        "vnp_TransactionNo": "15654117",
        "vnp_TransactionStatus": "00",
        "vnp_TxnRef": "CVN_46_1786518668",
    }

    sorted_params = sorted(params.items())
    hash_data = []
    for k, v in sorted_params:
        quoted_k = urllib.parse.quote_plus(str(k))
        quoted_v = urllib.parse.quote_plus(str(v))
        hash_data.append(f"{quoted_k}={quoted_v}")
    hash_string = "&".join(hash_data)

    calculated_hash = hmac.new(
        service.vnp_hash_secret.encode("utf-8"),
        hash_string.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    params["vnp_SecureHash"] = calculated_hash

    is_valid = service.verify_response(params)
    assert is_valid is True


def test_vnpay_verify_response_invalid_checksum():
    service = VNPayService()
    service.vnp_hash_secret = "NTDXCYCSAOPNANKALKQZICSVHTRLIKUX"

    params = {
        "vnp_Amount": "22770000",
        "vnp_ResponseCode": "00",
        "vnp_TxnRef": "CVN_46_1786518668",
        "vnp_SecureHash": "INVALID_CHECKSUM_HASH"
    }

    is_valid = service.verify_response(params)
    assert is_valid is False
