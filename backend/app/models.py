"""ORM models. All money columns are integer paise."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns tz-aware UTC (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


# ------------------------------------------------------------------ accounts

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(12))  # merchant | advertiser | admin
    name: Mapped[str] = mapped_column(String(120))
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey("merchants.id"), nullable=True)
    advertiser_id: Mapped[str | None] = mapped_column(ForeignKey("advertisers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    user: Mapped[User] = relationship()


# ------------------------------------------------------------------ merchants

class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    gstin: Mapped[str] = mapped_column(String(20))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    vpa: Mapped[str | None] = mapped_column(String(80), nullable=True)
    factorization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Busy hour: only the short sponsor tag plays (after the payment message), never a full ad.
    busy_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_categories: Mapped[list] = mapped_column(JSON, default=list)
    quiet_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    monthly_rental_paise: Mapped[int] = mapped_column(Integer, default=12500)
    rental_target_tx: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    devices: Mapped[list["Device"]] = relationship(back_populates="merchant")
    catalog: Mapped[list["CatalogItem"]] = relationship(back_populates="merchant", order_by="CatalogItem.created_at")


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    unit_price: Mapped[int] = mapped_column(Integer)
    hsn_sac: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(40))
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # ai | fallback | manual
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    merchant: Mapped[Merchant] = relationship(back_populates="catalog")


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64))
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    fw: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rssi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    merchant: Mapped[Merchant] = relationship(back_populates="devices")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    total_paise: Mapped[int] = mapped_column(Integer)
    factorize: Mapped[bool] = mapped_column(Boolean, default=True)
    sentinel: Mapped[dict] = mapped_column(JSON, default=dict)
    division: Mapped[dict] = mapped_column(JSON, default=dict)
    settlement: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(order_by="OrderItem.idx", cascade="all, delete-orphan")
    legs: Mapped[list["Leg"]] = relationship(order_by="Leg.seq", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(160))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    amount_paise: Mapped[int] = mapped_column(Integer)
    hsn_sac: Mapped[str] = mapped_column(String(10))
    supply_type: Mapped[str] = mapped_column(String(10))  # goods | services
    category: Mapped[str] = mapped_column(String(40))
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supplier_gstin: Mapped[str] = mapped_column(String(20))
    classification_source: Mapped[str] = mapped_column(String(10), default="manual")


class Leg(Base):
    __tablename__ = "legs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    of: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supply_type: Mapped[str] = mapped_column(String(10))
    supplier_gstin: Mapped[str] = mapped_column(String(20))
    amount_paise: Mapped[int] = mapped_column(Integer)
    item_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    provider: Mapped[str | None] = mapped_column(String(12), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    provider_txn_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    qr_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    rail: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payment_mode_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payer_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mdr_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


# ------------------------------------------------------------------ advertisers

class Advertiser(Base):
    __tablename__ = "advertisers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(10))  # local | brand
    category: Mapped[str] = mapped_column(String(40))
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TopUp(Base):
    __tablename__ = "topups"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    advertiser_id: Mapped[str] = mapped_column(ForeignKey("advertisers.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    provider: Mapped[str] = mapped_column(String(12))
    provider_ref: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    qr_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    advertiser_id: Mapped[str] = mapped_column(ForeignKey("advertisers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # audio | subvention
    name: Mapped[str] = mapped_column(String(120))
    prompt: Mapped[str] = mapped_column(Text, default="")
    lang: Mapped[str] = mapped_column(String(8), default="en")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_m: Mapped[int] = mapped_column(Integer, default=500)  # 0 = anywhere
    target_categories: Mapped[list] = mapped_column(JSON, default=list)
    sku_keywords: Mapped[list] = mapped_column(JSON, default=list)
    bid_paise: Mapped[int] = mapped_column(Integer)
    daily_cap_paise: Mapped[int] = mapped_column(Integer, default=0)  # 0 = no cap
    # Price of the short sponsor tag ("Sponsored by ...") played in busy hours; below bid_paise.
    tag_bid_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="generating")
    deploy_on_ready: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    advertiser: Mapped[Advertiser] = relationship()
    creative: Mapped["Creative | None"] = relationship(back_populates="campaign", uselist=False)


class Creative(Base):
    __tablename__ = "creatives"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    lang: Mapped[str] = mapped_column(String(8))
    script: Mapped[str] = mapped_column(Text)
    banner: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(10), default="ai")
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    audio_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice: Mapped[str | None] = mapped_column(String(60), nullable=True)
    voice_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    voice_fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign: Mapped[Campaign] = relationship(back_populates="creative")


class Hold(Base):
    """A reservation of advertiser money for one order.

    kind=audio: a metered play, committed only on a verified play_ack.
    kind=subvention: a brand cost-per-sale bid, committed at settlement.
    The id doubles as the playId sent to the device.
    """

    __tablename__ = "holds"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    advertiser_id: Mapped[str] = mapped_column(ForeignKey("advertisers.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(12))
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="reserved")  # reserved|committed|released
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ack_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # kind=audio (full ad, plays while the customer pays) / kind=tag (sponsor tag after the payment message)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)   # device confirmed a full, audible play
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # play sent to the device
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    advertiser: Mapped[Advertiser] = relationship()
    campaign: Mapped[Campaign] = relationship()


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creative_id: Mapped[str] = mapped_column(ForeignKey("creatives.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_id: Mapped[str] = mapped_column(String(40), index=True)
    ref: Mapped[str] = mapped_column(String(60), index=True)
    memo: Mapped[str] = mapped_column(String(160))
    account: Mapped[str] = mapped_column(String(60), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SentinelFlag(Base):
    __tablename__ = "sentinel_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ref: Mapped[str] = mapped_column(String(60))
    rule: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # info | warn | high
    action: Mapped[str] = mapped_column(String(20))  # allow | flag | block | deny_subsidy
    detail: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
