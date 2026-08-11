import hashlib
import hmac
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Any

# VNPay specification requires GMT+7 (Asia/Ho_Chi_Minh) timezone
VN_TZ = timezone(timedelta(hours=7))


class VNPayService:
    def __init__(self):
        self.vnp_tmn_code = os.getenv("VNPAY_TMN_CODE", "2QX7C60F")
        self.vnp_hash_secret = os.getenv("VNPAY_HASH_SECRET", "AWAATBAEAHWKYWTYVWWPBNHYVTWYQJJA")
        self.vnp_payment_url = os.getenv(
            "VNPAY_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
        )
        self.vnp_return_url = os.getenv(
            "VNPAY_RETURN_URL", "http://localhost:8443/api/v1/payments/vnpay-return"
        )

    def create_payment_url(
        self,
        vnp_txn_ref: str,
        amount: float | Decimal | str,
        order_info: str,
        client_ip: str = "127.0.0.1",
        return_url: str = None,
    ) -> str:
        """
        Build VNPay Sandbox payment URL with HMAC-SHA512 signature in GMT+7.
        """
        now = datetime.now(VN_TZ)
        create_date = now.strftime("%Y%m%d%H%M%S")
        expire_date = (now + timedelta(minutes=15)).strftime("%Y%m%d%H%M%S")

        vnp_amount = int(Decimal(str(amount)) * 100)

        vnp_params: Dict[str, Any] = {
            "vnp_Version": "2.1.0",
            "vnp_Command": "pay",
            "vnp_TmnCode": self.vnp_tmn_code,
            "vnp_Amount": vnp_amount,  # VNPay requires amount in VND * 100
            "vnp_CurrCode": "VND",
            "vnp_TxnRef": vnp_txn_ref,
            "vnp_OrderInfo": order_info,
            "vnp_OrderType": "other",
            "vnp_Locale": "vn",
            "vnp_ReturnUrl": return_url or self.vnp_return_url,
            "vnp_IpAddr": client_ip,
            "vnp_CreateDate": create_date,
            "vnp_ExpireDate": expire_date,
        }

        # 1. Sort dictionary alphabetically by key
        sorted_params = sorted(vnp_params.items())

        # 2. Build hash data string (query string format)
        hash_data = []
        query_data = []

        for k, v in sorted_params:
            if v is not None and str(v) != "":
                quoted_k = urllib.parse.quote_plus(str(k))
                quoted_v = urllib.parse.quote_plus(str(v))
                hash_data.append(f"{quoted_k}={quoted_v}")
                query_data.append(f"{quoted_k}={quoted_v}")

        hash_string = "&".join(hash_data)
        query_string = "&".join(query_data)

        # 3. Calculate HMAC-SHA512
        secure_hash = hmac.new(
            self.vnp_hash_secret.encode("utf-8"),
            hash_string.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

        payment_url = f"{self.vnp_payment_url}?{query_string}&vnp_SecureHash={secure_hash}"
        return payment_url

    def verify_response(self, query_params: Dict[str, str]) -> bool:
        """
        Verify HMAC-SHA512 signature from VNPay return / IPN callback.
        """
        vnp_secure_hash = query_params.get("vnp_SecureHash")
        if not vnp_secure_hash:
            return False

        # Filter out vnp_SecureHash and vnp_SecureHashType
        filtered_params = {
            k: v for k, v in query_params.items()
            if k not in ("vnp_SecureHash", "vnp_SecureHashType") and v is not None and str(v) != ""
        }

        sorted_params = sorted(filtered_params.items())
        hash_data = []
        for k, v in sorted_params:
            quoted_k = urllib.parse.quote_plus(str(k))
            quoted_v = urllib.parse.quote_plus(str(v))
            hash_data.append(f"{quoted_k}={quoted_v}")

        hash_string = "&".join(hash_data)

        calculated_hash = hmac.new(
            self.vnp_hash_secret.encode("utf-8"),
            hash_string.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

        return calculated_hash.lower() == vnp_secure_hash.lower()
