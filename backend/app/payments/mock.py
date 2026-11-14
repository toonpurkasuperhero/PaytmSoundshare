"""Test-mode provider (PAYMENT_PROVIDER=mock): no real money moves.

Payments are simulated through POST /api/mock/pay (merchant terminal or the paired
Soundbox simulator), which calls the settlement engine with the chosen rail.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from ..money import rupees_str
from .base import CreatedPayment, PaymentProvider, PaymentStatus


class MockProvider(PaymentProvider):
    name = "mock"

    def create_payment(self, *, ref: str, amount_paise: int, description: str,
                       expires_at: datetime, pos_id: str) -> CreatedPayment:
        qr = (f"upi://pay?pa=soundshare.{pos_id.lower()}@mockpaytm&pn={quote('SoundShare Test Mode')}"
              f"&am={rupees_str(amount_paise)}&cu=INR&tr={ref}&tn={quote(description[:40])}")
        return CreatedPayment(provider_ref=ref, qr_data=qr)

    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        return PaymentStatus(state="pending")
