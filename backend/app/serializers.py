from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import adx
from .config import settings
from .hub import hub
from .models import (Advertiser, Campaign, CatalogItem, Claim, Creative, Device, Hold, LedgerEntry, Leg,
                     Merchant, Order, TopUp, User)


def _today_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def user_dict(u: User) -> dict:
    return {"id": u.id, "phone": u.phone, "role": u.role, "name": u.name,
            "merchant_id": u.merchant_id, "advertiser_id": u.advertiser_id}


def leg_dict(l: Leg) -> dict:
    return {
        "id": l.id, "seq": l.seq, "of": l.of, "label": l.label, "reason": l.reason, "supply_type": l.supply_type,
        "supplier_gstin": l.supplier_gstin, "amount_paise": l.amount_paise, "item_ids": l.item_ids,
        "status": l.status, "provider": l.provider, "provider_ref": l.provider_ref, "qr_data": l.qr_data,
        "qr_image_url": l.qr_image_url, "checkout_url": l.checkout_url, "expires_at": l.expires_at,
        "rail": l.rail, "mdr_paise": l.mdr_paise, "paid_at": l.paid_at, "payer_ref": l.payer_ref,
    }


def order_dict(o: Order) -> dict:
    return {
        "id": o.id, "merchant_id": o.merchant_id, "device_id": o.device_id, "status": o.status,
        "total_paise": o.total_paise, "factorize": o.factorize, "created_at": o.created_at,
        "paid_at": o.paid_at, "settled_at": o.settled_at,
        "items": [{
            "id": i.id, "name": i.name, "qty": i.qty, "unit_price": i.unit_price, "amount_paise": i.amount_paise,
            "hsn_sac": i.hsn_sac, "supply_type": i.supply_type, "category": i.category, "brand": i.brand,
            "supplier_gstin": i.supplier_gstin, "classification_source": i.classification_source,
        } for i in o.items],
        "legs": [leg_dict(l) for l in o.legs],
        "settlement": o.settlement,
        "sentinel": o.sentinel,
        "division": o.division or {},
    }


def catalog_dict(c: CatalogItem) -> dict:
    return {"id": c.id, "name": c.name, "unit_price": c.unit_price, "hsn_sac": c.hsn_sac, "category": c.category,
            "brand": c.brand, "supply_type": "services" if c.hsn_sac.startswith("99") else "goods",
            "source": c.source}


def merchant_dict(db: Session, m: Merchant, with_stats: bool = False) -> dict:
    d = {
        "id": m.id, "name": m.name, "category": m.category, "gstin": m.gstin, "lat": m.lat, "lng": m.lng,
        "address": m.address, "lang": m.lang, "vpa": m.vpa,
        "busy_mode": m.busy_mode,
        "blocked_categories": m.blocked_categories or [], "quiet_hours": m.quiet_hours,
        "device_ids": [dv.id for dv in m.devices], "created_at": m.created_at,
    }
    if with_stats:
        from . import earnings
        settled = db.scalars(select(Order).where(Order.merchant_id == m.id, Order.status == "settled")).all()
        d["stats"] = {
            "tx_count": len(settled),
            "gross_paise": sum(o.total_paise for o in settled),
            "ad_revenue_paise": sum((o.settlement or {}).get("ad_revenue_paise", 0) for o in settled),
            **earnings.summary(db, m),
        }
    return d


def creative_dict(cr: Creative | None) -> dict | None:
    if not cr:
        return None
    return {
        "id": cr.id, "lang": cr.lang, "script": cr.script, "banner": cr.banner,
        "audio_hash": cr.audio_hash, "duration_ms": cr.duration_ms,
        "audio_url": f"/media/audio/{cr.audio_hash}.mp3" if cr.audio_hash else None,
        "offer_url": f"{settings.base_url}/api/offers/{cr.id}/claim",
        "source": cr.source, "fallback_reason": cr.fallback_reason, "model": cr.model,
        "voice": cr.voice, "voice_source": cr.voice_source, "voice_fallback_reason": cr.voice_fallback_reason,
    }


def _sum_holds(db: Session, *where) -> int:
    return db.execute(select(func.coalesce(func.sum(Hold.amount_paise), 0)).where(*where)).scalar_one()


def _count_holds(db: Session, *where) -> int:
    return db.execute(select(func.count(Hold.id)).where(*where)).scalar_one()


def campaign_dict(db: Session, c: Campaign) -> dict:
    claims = 0
    if c.creative:
        claims = db.execute(select(func.count(Claim.id)).where(Claim.creative_id == c.creative.id)).scalar_one()
    return {
        "id": c.id, "advertiser_id": c.advertiser_id, "advertiser_name": c.advertiser.name, "kind": c.kind,
        "name": c.name, "prompt": c.prompt, "lang": c.lang, "lat": c.lat, "lng": c.lng, "radius_m": c.radius_m,
        "target_categories": c.target_categories or [], "sku_keywords": c.sku_keywords or [],
        "bid_paise": c.bid_paise, "tag_bid_paise": adx.price(c, "tag"), "tag_bid_custom": c.tag_bid_paise is not None,
        "daily_cap_paise": c.daily_cap_paise, "status": c.status, "error": c.error,
        "created_at": c.created_at, "creative": creative_dict(c.creative),
        "stats": {
            "plays": _count_holds(db, Hold.campaign_id == c.id, Hold.kind == "audio", Hold.status == "committed"),
            "tag_plays": _count_holds(db, Hold.campaign_id == c.id, Hold.kind == "tag", Hold.status == "committed"),
            "spend_paise": _sum_holds(db, Hold.campaign_id == c.id, Hold.status == "committed"),
            "spent_today_paise": _sum_holds(db, Hold.campaign_id == c.id, Hold.status == "committed",
                                            Hold.created_at >= _today_start()),
            "claims": claims,
        },
    }


def advertiser_dict(db: Session, a: Advertiser, with_stats: bool = False) -> dict:
    available = adx.available_paise(db, a.id)
    from . import kyc
    d = {"id": a.id, "name": a.name, "type": a.type, "category": a.category, "lat": a.lat, "lng": a.lng,
         "address": a.address, "balance_paise": available, "created_at": a.created_at,
         "gstin": a.gstin, "kyc": kyc.status_dict(db, a)}
    if with_stats:
        mine = Hold.advertiser_id == a.id
        plays = _count_holds(db, mine, Hold.kind == "audio", Hold.status == "committed")
        audio_spend = _sum_holds(db, mine, Hold.kind == "audio", Hold.status == "committed")
        spend = _sum_holds(db, mine, Hold.status == "committed")
        active = db.scalars(select(Campaign).where(Campaign.advertiser_id == a.id, Campaign.status == "active")).all()
        avg_bid = (sum(c.bid_paise for c in active) / len(active)) if active else None
        topups = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
            LedgerEntry.account == f"adv:{a.id}", LedgerEntry.amount_paise > 0,
            LedgerEntry.ref.like("topup:%"))).scalar_one()
        claims = db.execute(select(func.count(Claim.id)).join(Creative, Claim.creative_id == Creative.id)
                            .join(Campaign, Creative.campaign_id == Campaign.id)
                            .where(Campaign.advertiser_id == a.id)).scalar_one()
        d["wallet"] = {
            "balance_paise": available,
            "reserved_paise": adx.reserved_paise(db, a.id),
            "spent_today_paise": _sum_holds(db, mine, Hold.status == "committed", Hold.created_at >= _today_start()),
            "daily_cap_total_paise": sum(c.daily_cap_paise for c in active),
            "burn_per_play_paise": round(audio_spend / plays) if plays else None,
            "est_plays_remaining": int(available // avg_bid) if avg_bid else None,
            "lifetime_topup_paise": topups,
            "lifetime_spend_paise": spend,
        }
        d["stats"] = {"plays": plays, "spend_paise": spend, "claims": claims,
                      "tag_plays": _count_holds(db, mine, Hold.kind == "tag", Hold.status == "committed"),
                      "released_plays": _count_holds(db, mine, Hold.kind == "audio", Hold.status == "released")}
    return d


def topup_dict(t: TopUp) -> dict:
    return {"id": t.id, "advertiser_id": t.advertiser_id, "amount_paise": t.amount_paise, "status": t.status,
            "provider": t.provider, "qr_data": t.qr_data, "checkout_url": t.checkout_url, "created_at": t.created_at}


def device_dict(d: Device) -> dict:
    return {"id": d.id, "merchant_id": d.merchant_id, "merchant_name": d.merchant.name, "name": d.name,
            "online": hub.online(d.id), "last_seen": d.last_seen, "fw": d.fw, "rssi": d.rssi,
            "created_at": d.created_at}


def ledger_invariant(db: Session) -> int:
    return db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))).scalar_one()


__all__ = ["advertiser_dict", "campaign_dict", "catalog_dict", "creative_dict", "device_dict",
           "ledger_invariant", "leg_dict", "merchant_dict", "order_dict", "topup_dict", "user_dict"]
