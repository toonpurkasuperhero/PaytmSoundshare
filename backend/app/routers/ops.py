"""Soundbox pairing, ledger, sentinel, admin stats, system status, payment webhooks."""
from __future__ import annotations

import asyncio
import logging
import secrets
import statistics
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, ledger, llm, sarvam, settlement
from ..config import settings
from ..db import get_db
from ..hub import hub
from ..models import Advertiser, Device, Hold, LedgerEntry, Merchant, Order, SentinelFlag, User
from ..payments import ProviderError, provider_by_name
from ..serializers import device_dict, ledger_invariant

router = APIRouter(prefix="/api")
log = logging.getLogger("zeromdr.ops")


# ------------------------------------------------------------------ devices

class DeviceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


def _provisioning(d: Device, token: str) -> dict:
    u = urlparse(settings.base_url)
    return {**device_dict(d), "token": token, "provisioning": {
        "host": u.hostname, "port": u.port or (443 if u.scheme == "https" else 80),
        "device_id": d.id, "token": token,
        "sim_url": f"{settings.base_url}/sim/?device={quote(d.id)}&token={quote(token)}"}}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    q = select(Device).order_by(Device.created_at)
    if user.role == "merchant":
        q = q.where(Device.merchant_id == user.merchant_id)
    elif user.role != "admin":
        raise HTTPException(403, "Not allowed for this account")
    return [device_dict(d) for d in db.scalars(q)]


@router.post("/devices", status_code=201)
def create_device(body: DeviceIn, db: Session = Depends(get_db), user: User = Depends(auth.require("merchant"))):
    for _ in range(10):
        did = f"SB-{secrets.token_hex(2).upper()}"
        if not db.get(Device, did):
            break
    else:
        raise HTTPException(500, "could not allocate a device id")
    token = secrets.token_urlsafe(18)
    d = Device(id=did, merchant_id=user.merchant_id, name=body.name.strip(), token_hash=auth.sha256(token))
    db.add(d)
    db.commit()
    return _provisioning(d, token)


def _own_device(db: Session, did: str, user: User) -> Device:
    d = db.get(Device, did)
    if not d:
        raise HTTPException(404, "device not found")
    auth.ensure_merchant(user, d.merchant_id, write=True)
    return d


@router.post("/devices/{did}/rotate-token")
def rotate_device_token(did: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    d = _own_device(db, did, user)
    token = secrets.token_urlsafe(18)
    d.token_hash = auth.sha256(token)
    db.commit()
    return _provisioning(d, token)


@router.delete("/devices/{did}", status_code=204)
def delete_device(did: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    db.delete(_own_device(db, did, user))
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ ledger / sentinel (admin)

admin_only = auth.require("admin")


@router.get("/ledger/balances")
def ledger_balances(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return ledger.balances(db)


@router.get("/ledger/entries")
def ledger_entries(ref: str | None = None, limit: int = Query(100, ge=1, le=1000),
                   db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return ledger.entries(db, ref, limit)


@router.get("/ledger/flows")
def ledger_flows(order_id: str | None = None, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return ledger.flows(db, order_id)


@router.get("/sentinel/flags")
def sentinel_flags(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
                   _: User = Depends(admin_only)):
    q = select(SentinelFlag).order_by(SentinelFlag.id.desc()).limit(limit)
    return [{"id": f.id, "ref": f.ref, "rule": f.rule, "severity": f.severity, "action": f.action,
             "detail": f.detail, "ts": f.ts} for f in db.scalars(q)]


def _pct(a: int, b: int) -> float | None:
    return round(100.0 * a / b, 3) if b else None


@router.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    settled = db.scalars(select(Order).where(Order.status == "settled")).all()
    ss = [o.settlement or {} for o in settled]
    gross = sum(o.total_paise for o in settled)
    mdr_ = sum(s.get("mdr_paise", 0) for s in ss)
    covered = sum(s.get("covered_paise", 0) for s in ss)
    liquidity = sum(s.get("ad_liquidity_paise", 0) for s in ss)
    platform = sum(s.get("platform_paise", 0) for s in ss)
    plays = db.execute(select(func.count(Hold.id)).where(Hold.kind == "audio", Hold.status == "committed")).scalar_one()
    released = db.execute(select(func.count(Hold.id)).where(Hold.kind == "audio", Hold.status == "released")).scalar_one()
    p = sorted(settlement.LATENCIES_MS)
    return {
        "orders": db.execute(select(func.count(Order.id))).scalar_one(),
        "settled_orders": len(settled),
        "gross_paise": gross,
        "avg_ticket_paise": round(gross / len(settled)) if settled else None,
        "mdr_paise": mdr_,
        "interchange_pct": _pct(mdr_, gross),
        "covered_paise": covered,
        "coverage_pct": _pct(covered, mdr_),
        "platform_paise": platform,
        "spread_pct": _pct(platform, liquidity),
        "ad_liquidity_paise": liquidity,
        "saved_by_factorization_paise": sum(s.get("saved_by_factorization_paise", 0) for s in ss),
        "plays": plays,
        "plays_released": released,
        "play_verification_pct": _pct(plays, plays + released),
        "devices_total": db.execute(select(func.count(Device.id))).scalar_one(),
        "devices_online": len([d for d in hub.online_ids()]),
        "merchants": db.execute(select(func.count(Merchant.id))).scalar_one(),
        "advertisers": db.execute(select(func.count(Advertiser.id))).scalar_one(),
        "ledger_invariant_paise": ledger_invariant(db),
        "shared_pool_paise": db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))
                                        .where(LedgerEntry.account == "shared_pool")).scalar_one(),
        "rental_paid_by_ads_paise": db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))
                                               .where(LedgerEntry.account == "soundbox_rental")).scalar_one(),
        "latency": {
            "p50_ms": round(statistics.median(p), 1) if p else None,
            "p95_ms": round(p[min(len(p) - 1, int(len(p) * 0.95))], 1) if p else None,
            "last_ms": round(settlement.LATENCIES_MS[-1], 1) if p else None,
            "samples": len(p),
        },
    }


@router.get("/system/status")
def system_status(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    try:
        provider_by_name(settings.payment_provider)
        prov = {"ok": True, "detail": "configured"}
    except ProviderError as e:
        prov = {"ok": False, "detail": str(e)}
    try:
        db.execute(select(func.count(User.id))).scalar_one()
        db_state = "ok"
    except Exception as e:  # pragma: no cover
        db_state = f"error: {e}"
    return {
        "provider": {"name": settings.payment_provider, "mode": settings.provider_mode, **prov},
        "ai": llm.health.as_dict(),
        "sarvam": sarvam.health.as_dict(),
        "devices": {"total": db.execute(select(func.count(Device.id))).scalar_one(),
                    "online": len(hub.online_ids())},
        "db": db_state,
        "base_url": settings.base_url,
    }


# ------------------------------------------------------------------ payment webhooks (public, signed)

async def _webhook(provider: str, request: Request) -> dict:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        refs = provider_by_name(provider).webhook_refs(headers, body)
    except ProviderError as e:
        log.warning("%s webhook rejected: %s", provider, e)
        raise HTTPException(400, "invalid signature or provider not configured")
    for ref in refs:
        await asyncio.to_thread(settlement.refresh_by_provider_ref, provider, ref)
    return {"ok": True, "refs": refs}


@router.post("/webhooks/paytm")
async def paytm_webhook(request: Request):
    return await _webhook("paytm", request)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    return await _webhook("razorpay", request)
