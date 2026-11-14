from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import CreatedPayment, PaymentProvider, PaymentStatus, ProviderError

__all__ = ["CreatedPayment", "PaymentProvider", "PaymentStatus", "ProviderError", "get_provider", "provider_by_name"]


@lru_cache(maxsize=4)
def provider_by_name(name: str) -> PaymentProvider:
    if name == "paytm":
        from .paytm import PaytmProvider
        return PaytmProvider()
    if name == "razorpay":
        from .razorpay import RazorpayProvider
        return RazorpayProvider()
    from .mock import MockProvider
    return MockProvider()


def get_provider() -> PaymentProvider:
    return provider_by_name(settings.payment_provider)
