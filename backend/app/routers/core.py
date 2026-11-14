"""Config, QR rendering, merchants + catalog, AI bill parsing/planning, orders, test-mode payments."""
from __future__ import annotations

import io

import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import announcer, auth, earnings, factorizer, languages, llm, mdr, sarvam, settlement
from ..config import settings
from ..db import get_db, money_lock
from ..models import CatalogItem, Device, Leg, Merchant, Order, User
from ..money import new_id
from ..payments import PaymentStatus, ProviderError
from ..serializers import catalog_dict, merchant_dict, order_dict

router = APIRouter(prefix="/api")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


@router.get("/config")
def get_config():
    return {
        "provider": settings.payment_provider,
        "provider_mode": settings.provider_mode,
        "rails": mdr.RAILS,          # payment methods the test-mode simulator can pick
        "base_url": settings.base_url,
        "ai": {"configured": llm.configured(), "text_model": settings.gemini_model,
               "tts_model": settings.gemini_tts_model},
        "sarvam": {"configured": sarvam.configured()},
        "languages": languages.public(),
    }


@router.get("/announce/{order_id}.mp3")
def announcement(order_id: str, db: Session = Depends(get_db)):
    """Full-sentence payment announcement in the merchant's language (Sarvam voice + chime).
    Bound to a real order, so it can't be used to synthesise arbitrary text."""
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "order not found")
    lang = db.get(Merchant, o.merchant_id).lang
    try:
        path = announcer.ensure(lang, o.total_paise)
    except Exception as e:  # device falls back to its local clips
        raise HTTPException(503, f"announcement unavailable: {e}")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/qr.svg")
def qr_svg(data: str = Query(..., max_length=2000), scale: int = Query(8, ge=1, le=40)):
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=scale, border=2, dark="#000", light="#fff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------ merchants

class MerchantPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    blocked_categories: list[str] | None = None
    busy_mode: bool | None = None
    lang: str | None = Field(None, pattern=languages.PATTERN)
    vpa: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    address: str | None = Field(None, max_length=300)


def _merchant(db: Session, mid: str) -> Merchant:
    m = db.get(Merchant, mid)
    if not m:
        raise HTTPException(404, "merchant not found")
    return m


@router.get("/merchants")
def list_merchants(db: Session = Depends(get_db), _: User = Depends(auth.require("admin"))):
    return [merchant_dict(db, m, with_stats=True) for m in db.scalars(select(Merchant).order_by(Merchant.created_at))]


@router.get("/merchants/{mid}")
def get_merchant(mid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid)
    return merchant_dict(db, _merchant(db, mid), with_stats=True)


@router.patch("/merchants/{mid}")
def patch_merchant(mid: str, body: MerchantPatch, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid, write=True)
    m = _merchant(db, mid)
    data = body.model_dump(exclude_unset=True)
    if "vpa" in data and data["vpa"] is not None:
        data["vpa"] = auth.normalize_vpa(data["vpa"])
    if "blocked_categories" in data and data["blocked_categories"] is not None:
        data["blocked_categories"] = sorted({c.strip().lower() for c in data["blocked_categories"] if c.strip()})
    for k, v in data.items():
        setattr(m, k, v)
    if "name" in data:
        user.name = m.name
    db.commit()
    return merchant_dict(db, m, with_stats=True)


# ------------------------------------------------------------------ catalog

class CatalogIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    unit_price: int = Field(..., gt=0, le=100_000_000)
    hsn_sac: str | None = Field(None, max_length=10)
    category: str | None = Field(None, max_length=40)
    brand: str | None = Field(None, max_length=40)


class CatalogPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    unit_price: int | None = Field(None, gt=0, le=100_000_000)
    hsn_sac: str | None = Field(None, max_length=10)
    category: str | None = Field(None, max_length=40)
    brand: str | None = Field(None, max_length=40)


@router.get("/merchants/{mid}/earnings")
def get_earnings(mid: str, days: int = Query(30, ge=7, le=120), db: Session = Depends(get_db),
                 user: User = Depends(auth.current_user)):
    """Ad-earnings tracker: rental paid by ads, then what the merchant earned."""
    auth.ensure_merchant(user, mid)
    return earnings.tracker(db, _merchant(db, mid), days)


@router.get("/merchants/{mid}/catalog")
def get_catalog(mid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid)
    return [catalog_dict(c) for c in _merchant(db, mid).catalog]


@router.post("/merchants/{mid}/catalog", status_code=201)
def add_catalog_item(mid: str, body: CatalogIn, db: Session = Depends(get_db),
                     user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid, write=True)
    _merchant(db, mid)
    item = body.model_dump()
    row = CatalogItem(id=new_id("C", 4), merchant_id=mid, name=item["name"].strip(), unit_price=item["unit_price"],
                      hsn_sac=(item.get("hsn_sac") or "").strip() or "0000",
                      category=(item.get("category") or "general").strip().lower(), brand=item.get("brand"),
                      source="manual")
    db.add(row)
    db.commit()
    return catalog_dict(row)


def _catalog_item(db: Session, mid: str, item_id: str) -> CatalogItem:
    c = db.get(CatalogItem, item_id)
    if not c or c.merchant_id != mid:
        raise HTTPException(404, "catalog item not found")
    return c


@router.patch("/merchants/{mid}/catalog/{item_id}")
def edit_catalog_item(mid: str, item_id: str, body: CatalogPatch, db: Session = Depends(get_db),
                      user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid, write=True)
    c = _catalog_item(db, mid, item_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    return catalog_dict(c)


@router.delete("/merchants/{mid}/catalog/{item_id}", status_code=204)
def delete_catalog_item(mid: str, item_id: str, db: Session = Depends(get_db),
                        user: User = Depends(auth.current_user)):
    auth.ensure_merchant(user, mid, write=True)
    db.delete(_catalog_item(db, mid, item_id))
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ AI bill parsing

class ItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    qty: int = Field(1, ge=1, le=10_000)
    unit_price: int = Field(..., ge=0, le=100_000_000, description="paise")
    hsn_sac: str | None = Field(None, max_length=10)
    category: str | None = Field(None, max_length=40)
    brand: str | None = Field(None, max_length=40)
    supplier_gstin: str | None = Field(None, max_length=20)
    catalog_item_id: str | None = None
    classification_source: str | None = None


def _own_merchant(db: Session, user: User) -> Merchant:
    if user.role != "merchant" or not user.merchant_id:
        raise HTTPException(403, "Merchant account required")
    return _merchant(db, user.merchant_id)


@router.post("/bills/parse")
async def parse_bill(request: Request, user: User = Depends(auth.require("merchant"))):
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("image")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(422, "Attach the bill photo as 'image'")
        mime = (upload.content_type or "").lower()
        if mime not in IMAGE_TYPES:
            raise HTTPException(415, "Bill photo must be JPEG, PNG, WEBP or HEIC")
        data = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Bill photo must be 8 MB or smaller")
        try:
            return await run_in_threadpool(factorizer.parse_image, data, mime)
        except factorizer.ParseFailed as e:
            raise HTTPException(502, str(e))
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "Send {\"text\": ...} or a multipart 'image'")
    text = str((body or {}).get("text") or "").strip()
    if not text or len(text) > 8000:
        raise HTTPException(422, "Bill text must be 1-8000 characters")
    return await run_in_threadpool(factorizer.parse_text, text)


# ------------------------------------------------------------------ orders

class OrderIn(BaseModel):
    """One bill, one QR for the full amount. (Old split fields such as `legs` are ignored.)"""
    device_id: str | None = None
    items: list[ItemIn] = Field(..., min_length=1, max_length=100)


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, db: Session = Depends(get_db), user: User = Depends(auth.require("merchant"))):
    m = _own_merchant(db, user)
    try:
        with money_lock:
            order, out = settlement.create_order(db, m.id, [i.model_dump() for i in body.items], body.device_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ProviderError as e:
        raise HTTPException(502, f"Payment provider error: {e}")
    out.flush()
    return order_dict(order)


@router.get("/orders")
def list_orders(merchant_id: str | None = None, limit: int = Query(20, ge=1, le=200),
                db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    q = select(Order).order_by(Order.created_at.desc()).limit(limit)
    if user.role == "merchant":
        q = q.where(Order.merchant_id == user.merchant_id)
    elif user.role == "admin":
        if merchant_id:
            q = q.where(Order.merchant_id == merchant_id)
    else:
        raise HTTPException(403, "Not allowed for this account")
    return [order_dict(o) for o in db.scalars(q)]


def _order(db: Session, oid: str, user: User, write: bool = False) -> Order:
    o = db.get(Order, oid)
    if not o:
        raise HTTPException(404, "order not found")
    auth.ensure_merchant(user, o.merchant_id, write=write)
    return o


@router.get("/orders/{oid}")
def get_order(oid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    return order_dict(_order(db, oid, user))


@router.post("/orders/{oid}/cancel")
def cancel_order(oid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    _order(db, oid, user, write=True)
    settlement.cancel_order(oid)
    db.commit()  # end txn so we read the other session's writes
    db.expire_all()  # and drop stale cached objects (expire_on_commit is off)
    return order_dict(_order(db, oid, user))


@router.post("/orders/{oid}/refresh")
def refresh_order(oid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    o = _order(db, oid, user, write=True)
    for leg in o.legs:
        if leg.status == "active" and leg.provider and leg.provider != "mock" and leg.provider_ref:
            settlement.refresh_by_provider_ref(leg.provider, leg.provider_ref)
    db.commit()
    db.expire_all()
    return order_dict(_order(db, oid, user))


class MockPayIn(BaseModel):
    leg_id: str
    rail: str = Field(..., description="payment method the simulated customer uses")
    payer: str | None = Field(None, max_length=120)
    device_token: str | None = Field(None, max_length=200)


@router.post("/mock/pay")
def mock_pay(body: MockPayIn, db: Session = Depends(get_db), user: User | None = Depends(auth.optional_user)):
    """Test mode only: simulate the customer paying a leg."""
    if settings.payment_provider != "mock":
        raise HTTPException(409, "Simulated payments are only available in test mode (PAYMENT_PROVIDER=mock)")
    leg = db.get(Leg, body.leg_id)
    if not leg:
        raise HTTPException(404, "leg not found")
    order = db.get(Order, leg.order_id)
    allowed = bool(user and user.role == "merchant" and user.merchant_id == order.merchant_id)
    if not allowed and body.device_token and order.device_id:
        dev = db.get(Device, order.device_id)
        allowed = bool(dev and dev.token_hash == auth.sha256(body.device_token))
    if not allowed:
        raise HTTPException(403, "Only the merchant or its paired Soundbox can simulate this payment")
    if leg.provider != "mock":
        raise HTTPException(409, f"leg belongs to provider '{leg.provider}'; pay it with a real app")
    if leg.status != "active":
        raise HTTPException(409, f"leg is {leg.status}, not active")
    if body.rail not in mdr.RAILS or body.rail == "UNKNOWN":
        raise HTTPException(422, f"rail must be one of {[r for r in mdr.RAILS if r != 'UNKNOWN']}")
    rail = body.rail
    settlement.confirm_leg(leg.id, PaymentStatus("paid", rail=rail, payer_ref=body.payer or None,
                                                 txn_id=new_id("TESTTXN", 6)))
    db.commit()
    db.expire_all()  # settlement ran in another session: re-read
    return order_dict(db.get(Order, leg.order_id))
