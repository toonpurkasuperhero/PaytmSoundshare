"""Razorpay fallback provider.

Modes:
  payment_link (default): Payment Links API. The QR encodes the hosted checkout
      short URL. Works fully in TEST mode (pay with UPI id success@razorpay or test cards).
  upi_qr: QR Codes API (single-use, fixed amount). Live mode only for real UPI
      apps. The UPI string is decoded from Razorpay's QR image when the optional
      `zxing-cpp` + `pillow` packages are installed; otherwise devices fall back
      to showing the image URL.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
from datetime import datetime, timezone

import httpx

from ..config import settings
from .base import CreatedPayment, PaymentProvider, PaymentStatus, ProviderError

log = logging.getLogger("zeromdr.razorpay")
API = "https://api.razorpay.com/v1"


def razorpay_rail(p: dict) -> str:
    method = (p.get("method") or "").lower()
    if method == "upi":
        acct = str((p.get("upi") or {}).get("payer_account_type") or "").lower()
        if "credit" in acct:
            return "UPI_RUPAY_CC"
        if "wallet" in acct or "ppi" in acct:
            return "UPI_PPI"
        return "UPI_BANK"
    if method == "card":
        card = p.get("card") or {}
        return "DEBIT_CARD" if (card.get("type") or "").lower() == "debit" else "CREDIT_CARD"
    if method == "wallet":
        return "UPI_PPI"
    if method in ("emi", "cardless_emi", "paylater"):
        return "CREDIT_CARD"  # credit products: charged at the credit rate
    if method == "netbanking":
        return "NET_BANKING"
    return "UNKNOWN"


def _payer(p: dict) -> str | None:
    return p.get("vpa") or (p.get("upi") or {}).get("vpa") or p.get("contact")


def _decode_qr_image(url: str) -> str | None:
    try:
        import zxingcpp  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(httpx.get(url, timeout=10).content))
        res = zxingcpp.read_barcodes(img)
        return res[0].text if res else None
    except Exception as e:
        log.warning("QR decode failed: %s", e)
        return None


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    def __init__(self) -> None:
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            raise ProviderError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured")
        self.mode = settings.razorpay_mode
        self.client = httpx.Client(base_url=API, auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                                   timeout=15)

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.client.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
                msg = f"{err.get('code')}: {err.get('description')}"
            except ValueError:
                msg = r.text[:200]
            raise ProviderError(f"Razorpay {method} {path} -> {r.status_code} {msg}")
        return r.json()

    def create_payment(self, *, ref: str, amount_paise: int, description: str,
                       expires_at: datetime, pos_id: str) -> CreatedPayment:
        now = datetime.now(timezone.utc)
        if self.mode == "upi_qr":
            body = {
                "type": "upi_qr", "name": "SoundShare", "usage": "single_use", "fixed_amount": True,
                "payment_amount": amount_paise, "description": description[:250],
                "close_by": int(max(expires_at, now).timestamp()) + 120, "notes": {"ref": ref, "pos": pos_id},
            }
            qr = self._req("POST", "/payments/qr_codes", json=body)
            image = qr.get("image_url")
            return CreatedPayment(provider_ref=qr["id"], qr_data=_decode_qr_image(image) if image else None,
                                  qr_image_url=image)
        body = {
            "amount": amount_paise, "currency": "INR", "accept_partial": False,
            "reference_id": ref, "description": description[:2000],
            "notify": {"sms": False, "email": False}, "reminder_enable": False,
            "notes": {"ref": ref, "pos": pos_id},
        }
        if (expires_at - now).total_seconds() > 16 * 60:  # Razorpay requires >15 min
            body["expire_by"] = int(expires_at.timestamp())
        link = self._req("POST", "/payment_links", json=body)
        return CreatedPayment(provider_ref=link["id"], qr_data=link["short_url"], checkout_url=link["short_url"])

    def _payment(self, payment_id: str) -> dict:
        return self._req("GET", f"/payments/{payment_id}", params={"expand[]": "card"})

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        try:
            if provider_ref.startswith("qr_"):
                qr = self._req("GET", f"/payments/qr_codes/{provider_ref}")
                pays = self._req("GET", f"/payments/qr_codes/{provider_ref}/payments").get("items", [])
                captured = [p for p in pays if p.get("status") == "captured"]
                if captured:
                    p = captured[0]
                    return PaymentStatus("paid", razorpay_rail(p), _payer(p), p["id"], p)
                if qr.get("status") == "closed":
                    return PaymentStatus("expired", raw=qr)
                return PaymentStatus("pending")
            link = self._req("GET", f"/payment_links/{provider_ref}")
            st = link.get("status")
            if st == "paid":
                pays = link.get("payments") or []
                pid = next((x.get("payment_id") for x in pays if x.get("status") == "captured"),
                           pays[0].get("payment_id") if pays else None)
                p = self._payment(pid) if pid else {}
                return PaymentStatus("paid", razorpay_rail(p), _payer(p), pid, p)
            if st in ("expired", "cancelled"):
                return PaymentStatus("expired" if st == "expired" else "failed", raw=link)
            return PaymentStatus("pending")
        except (ProviderError, httpx.HTTPError) as e:
            log.warning("status poll failed for %s: %s", provider_ref, e)
            return PaymentStatus("pending")

    def webhook_refs(self, headers: dict, body: bytes) -> list[str]:
        secret = settings.razorpay_webhook_secret
        sig = headers.get("x-razorpay-signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, sig):
            raise ProviderError("Invalid Razorpay webhook signature")
        evt = json.loads(body)
        payload = evt.get("payload", {})
        refs = []
        for k in ("payment_link", "qr_code"):
            ent = (payload.get(k) or {}).get("entity") or {}
            if ent.get("id"):
                refs.append(ent["id"])
        return refs

    def cancel(self, provider_ref: str) -> None:
        try:
            if provider_ref.startswith("qr_"):
                self._req("POST", f"/payments/qr_codes/{provider_ref}/close")
            else:
                self._req("POST", f"/payment_links/{provider_ref}/cancel")
        except (ProviderError, httpx.HTTPError) as e:
            log.info("cancel %s: %s", provider_ref, e)
