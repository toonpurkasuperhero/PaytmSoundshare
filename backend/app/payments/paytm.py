"""Paytm Payment Gateway: Dynamic QR (Create QR Code API) + Transaction Status API v3.

Docs: https://paytmpayments.com/docs/dynamic-qr-code-payments
Note: Dynamic QR must be enabled on the MID by Paytm.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib.parse import parse_qs

import httpx

from ..config import settings
from ..money import rupees_str
from .base import CreatedPayment, PaymentProvider, PaymentStatus, ProviderError
from .paytm_checksum import generate_signature, verify_signature

log = logging.getLogger("zeromdr.paytm")

_MODE_TO_RAIL = {"CC": "CREDIT_CARD", "DC": "DEBIT_CARD", "PPI": "UPI_PPI", "NB": "NET_BANKING",
                 "BALANCE": "UPI_PPI", "PAYTM_DIGITAL_CREDIT": "CREDIT_CARD", "EMI": "CREDIT_CARD"}


def paytm_rail(body: dict) -> str:
    mode = str(body.get("paymentMode") or "").upper()
    if mode == "UPI":
        hints = " ".join(str(body.get(k) or "") for k in
                         ("cardScheme", "upiPayerAccountType", "accountType", "payerAccountType", "instrumentType")).upper()
        if "RUPAY" in hints or "CREDIT" in hints:
            return "UPI_RUPAY_CC"
        if "PPI" in hints or "WALLET" in hints:
            return "UPI_PPI"
        return "UPI_BANK"
    return _MODE_TO_RAIL.get(mode, "UNKNOWN")


class PaytmProvider(PaymentProvider):
    name = "paytm"

    def __init__(self) -> None:
        if not (settings.paytm_mid and settings.paytm_merchant_key):
            raise ProviderError("PAYTM_MID / PAYTM_MERCHANT_KEY are not configured")
        self.mid = settings.paytm_mid
        self.key = settings.paytm_merchant_key
        self.base = settings.paytm_base_url.rstrip("/")
        self.client = httpx.Client(timeout=15)

    def _post(self, path: str, body: dict, head: dict) -> dict:
        body_str = json.dumps(body, separators=(",", ":"))
        head = {**head, "signature": generate_signature(body_str, self.key)}
        payload = '{"body":' + body_str + ',"head":' + json.dumps(head, separators=(",", ":")) + "}"
        r = self.client.post(self.base + path, content=payload, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()

    def create_payment(self, *, ref: str, amount_paise: int, description: str,
                       expires_at: datetime, pos_id: str) -> CreatedPayment:
        body = {
            "mid": self.mid,
            "orderId": ref,
            "amount": rupees_str(amount_paise),
            "businessType": "UPI_QR_CODE",
            "posId": f"{settings.paytm_store_id}_{pos_id}",
            "orderDetails": description[:100],
            "imageRequired": False,
        }
        head = {"clientId": settings.paytm_client_id, "version": "v1"}
        try:
            data = self._post("/paymentservices/qr/create", body, head)
        except httpx.HTTPError as e:
            raise ProviderError(f"Paytm Create QR failed: {e}") from e
        res = data.get("body", {})
        info = res.get("resultInfo", {})
        if info.get("resultStatus") != "SUCCESS" or not res.get("qrData"):
            raise ProviderError(f"Paytm Create QR: {info.get('resultCode')} {info.get('resultMsg')}")
        return CreatedPayment(provider_ref=ref, qr_data=res["qrData"])

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        try:
            data = self._post("/v3/order/status", {"mid": self.mid, "orderId": provider_ref}, {})
        except httpx.HTTPError as e:
            log.warning("status poll failed for %s: %s", provider_ref, e)
            return PaymentStatus(state="pending")
        body = data.get("body", {})
        status = (body.get("resultInfo") or {}).get("resultStatus")
        if status == "TXN_SUCCESS":
            return PaymentStatus(state="paid", rail=paytm_rail(body), txn_id=body.get("txnId"),
                                 payer_ref=body.get("vpa") or body.get("payerVpa"), raw=body)
        if status == "TXN_FAILURE":
            return PaymentStatus(state="failed", raw=body)
        return PaymentStatus(state="pending", raw=body)

    def webhook_refs(self, headers: dict, body: bytes) -> list[str]:
        params = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        if not params:
            try:
                params = json.loads(body)
            except ValueError:
                params = {}
        checksum = params.get("CHECKSUMHASH")
        if not checksum or not verify_signature(params, self.key, checksum):
            raise ProviderError("Invalid Paytm webhook checksum")
        ref = params.get("ORDERID")
        return [ref] if ref else []
