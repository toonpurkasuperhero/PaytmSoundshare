from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class ProviderError(RuntimeError):
    pass


@dataclass
class CreatedPayment:
    provider_ref: str
    qr_data: str | None
    qr_image_url: str | None = None
    checkout_url: str | None = None


@dataclass
class PaymentStatus:
    state: str  # pending | paid | failed | expired
    rail: str | None = None
    payer_ref: str | None = None
    txn_id: str | None = None
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    name: str = "base"

    @abstractmethod
    def create_payment(self, *, ref: str, amount_paise: int, description: str,
                       expires_at: datetime, pos_id: str) -> CreatedPayment: ...

    @abstractmethod
    def fetch_status(self, provider_ref: str) -> PaymentStatus: ...

    def webhook_refs(self, headers: dict, body: bytes) -> list[str]:
        """Verify a webhook and return the provider refs it concerns.
        The caller re-confirms each ref through fetch_status (source of truth)."""
        raise NotImplementedError

    def cancel(self, provider_ref: str) -> None:  # best effort
        return None
