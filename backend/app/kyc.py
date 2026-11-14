"""Advertiser KYC: ads go live only for advertisers with a VERIFIED GSTIN and the minimum deposit.

Layers:
1. On sign-up / GSTIN change: structural + check-digit validation (app.gstin). Fakes are rejected instantly.
2. Verification: `verify_with_provider` is the plug-in point for Paytm's existing merchant KYC
   pipeline or a GST Suvidha Provider (GSP) lookup (active status, legal name match). Until one is
   connected, an admin reviews and approves/rejects in the admin console (method "manual").
3. Deposit: at least settings.advertiser_min_deposit_paise topped up before any ad serves.
Campaigns created before both are met wait as status "pending_kyc" and go live automatically.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .hub import hub
from .models import Advertiser, Campaign, LedgerEntry, utcnow
from .money import inr

log = logging.getLogger("zeromdr.kyc")


def deposited(db: Session, advertiser_id: str) -> int:
    """Total ever topped up into the advertiser's wallet."""
    return db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.account == f"adv:{advertiser_id}", LedgerEntry.amount_paise > 0,
        LedgerEntry.ref.like("topup:%"))).scalar_one()


def blockers(db: Session, a: Advertiser) -> list[str]:
    out = []
    if a.kyc_status == "rejected":
        out.append("GST verification was rejected" + (f": {a.kyc_note}" if a.kyc_note else ""))
    elif a.kyc_status != "verified":
        out.append("GST verification pending" if a.gstin else "Add your GSTIN for verification")
    dep, need = deposited(db, a.id), settings.advertiser_min_deposit_paise
    if dep < need:
        out.append(f"Deposit at least {inr(need)} to go live ({inr(dep)} so far)")
    return out


def can_go_live(db: Session, a: Advertiser) -> bool:
    return not blockers(db, a)


def status_dict(db: Session, a: Advertiser) -> dict:
    b = blockers(db, a)
    return {"status": a.kyc_status, "gstin": a.gstin, "note": a.kyc_note, "method": a.kyc_method,
            "verified_at": a.kyc_verified_at, "deposit_paise": deposited(db, a.id),
            "min_deposit_paise": settings.advertiser_min_deposit_paise, "blockers": b, "can_go_live": not b}


def verify_with_provider(a: Advertiser) -> tuple[str, str | None] | None:
    """Plug-in point for Paytm's KYC pipeline / a GSP API. Return ("verified"|"rejected", note), or
    None to leave the advertiser for manual review. No provider is connected yet."""
    return None


def submit(db: Session, a: Advertiser, gstin_: str) -> None:
    """New or changed GSTIN: back to verification (and off the air until verified again)."""
    changed = a.gstin != gstin_
    a.gstin = gstin_
    if changed or a.kyc_status != "verified":
        a.kyc_status, a.kyc_note, a.kyc_method, a.kyc_verified_at = "pending", None, None, None
        _hold_live_campaigns(db, a)
    result = verify_with_provider(a)
    if result:
        (approve if result[0] == "verified" else reject)(db, a, note=result[1], method="provider")


def approve(db: Session, a: Advertiser, note: str | None = None, method: str = "manual") -> None:
    a.kyc_status, a.kyc_note, a.kyc_method, a.kyc_verified_at = "verified", note, method, utcnow()
    activate_ready(db, a)


def reject(db: Session, a: Advertiser, note: str | None = None, method: str = "manual") -> None:
    a.kyc_status, a.kyc_note, a.kyc_method, a.kyc_verified_at = "rejected", note, method, None
    _hold_live_campaigns(db, a)


def _hold_live_campaigns(db: Session, a: Advertiser) -> None:
    for c in db.scalars(select(Campaign).where(Campaign.advertiser_id == a.id, Campaign.status == "active")):
        c.status, c.deploy_on_ready = "pending_kyc", True


def activate_ready(db: Session, a: Advertiser) -> int:
    """Put waiting campaigns live once verification + deposit are both satisfied."""
    if not can_go_live(db, a):
        return 0
    n = 0
    for c in db.scalars(select(Campaign).where(Campaign.advertiser_id == a.id, Campaign.status == "pending_kyc")):
        if c.kind == "audio" and not (c.creative and c.creative.audio_hash):
            continue
        c.status = "active"
        n += 1
        if c.creative and c.creative.audio_hash:
            hub.broadcast_cache_audio(c.creative.audio_hash)
    if n:
        hub.emit("campaign_update", advertiser_id=a.id, status="active")
    return n
