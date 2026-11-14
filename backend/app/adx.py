"""Ad exchange: picks the audio ad and brand subvention sponsors for a checkout.

Audio slot (one per checkout): local advertisers inside their geofence, billed per
verified play. score = bid x proximity.
Subvention slot: brand campaigns whose category/SKU keywords match an item in
the cart (cost per sale), chosen by bid until the MDR shortfall is covered.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ledger
from .models import Campaign, Hold, Merchant, OrderItem, utcnow

MAX_SPONSORS = 2
FREQ_CAP_PER_HOUR = 30


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def reserved_paise(db: Session, advertiser_id: str) -> int:
    return db.execute(
        select(func.coalesce(func.sum(Hold.amount_paise), 0))
        .where(Hold.advertiser_id == advertiser_id, Hold.status == "reserved")
    ).scalar_one()


def available_paise(db: Session, advertiser_id: str) -> int:
    return ledger.balance(db, f"adv:{advertiser_id}") - reserved_paise(db, advertiser_id)


def _spent_today(db: Session, campaign_id: str) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.coalesce(func.sum(Hold.amount_paise), 0))
        .where(Hold.campaign_id == campaign_id, Hold.status.in_(("reserved", "committed")), Hold.created_at >= start)
    ).scalar_one()


def distance_m(c: Campaign, m: Merchant) -> float | None:
    if c.lat is None or c.lng is None:
        return None
    return haversine_m(c.lat, c.lng, m.lat, m.lng)


def _in_geofence(c: Campaign, m: Merchant) -> bool:
    if not c.radius_m:
        return True
    d = distance_m(c, m)
    return d is None or d <= c.radius_m


TAG_PRICE_SHARE = 0.75  # default sponsor-tag price as a share of the full-ad price


def price(c: Campaign, fmt: str = "ad") -> int:
    """What one play costs: fmt='ad' (full ad after the payment message) or 'tag' (short sponsor tag)."""
    if fmt == "tag":
        return c.tag_bid_paise or max(1, round(c.bid_paise * TAG_PRICE_SHARE))
    return c.bid_paise


def _base_eligible(db: Session, c: Campaign, m: Merchant, cost: int | None = None) -> bool:
    cost = c.bid_paise if cost is None else cost
    adv = c.advertiser
    if c.status != "active" or adv.kyc_status != "verified":  # unverified advertisers never serve
        return False
    if adv.category in (m.blocked_categories or []):
        return False
    if adv.type == "local" and adv.category == m.category:  # never advertise a rival at the counter
        return False
    if not _in_geofence(c, m):
        return False
    if c.daily_cap_paise and _spent_today(db, c.id) + cost > c.daily_cap_paise:
        return False
    return available_paise(db, adv.id) >= cost


def in_quiet_hours(m: Merchant, now: datetime | None = None) -> bool:
    qh = m.quiet_hours or {}
    if not qh.get("start") or not qh.get("end"):
        return False
    ist = (now or datetime.now(timezone.utc)) + timedelta(hours=5, minutes=30)
    cur = ist.strftime("%H:%M")
    s, e = qh["start"], qh["end"]
    return (s <= cur < e) if s <= e else (cur >= s or cur < e)


def pick_audio(db: Session, m: Merchant, device_id: str | None, fmt: str = "ad") -> Campaign | None:
    """Best audio campaign for this counter. fmt='ad' needs a voiced creative; fmt='tag' only a name."""
    best, best_score = None, -1.0
    hour_ago = utcnow() - timedelta(hours=1)
    for c in db.scalars(select(Campaign).where(Campaign.kind == "audio", Campaign.status == "active")):
        if not c.creative or not _base_eligible(db, c, m, price(c, fmt)):
            continue
        if fmt == "ad" and not c.creative.audio_hash:
            continue
        if device_id:
            plays = db.execute(select(func.count(Hold.id)).where(
                Hold.campaign_id == c.id, Hold.device_id == device_id, Hold.created_at >= hour_ago)).scalar_one()
            if plays >= FREQ_CAP_PER_HOUR:
                continue
        d = distance_m(c, m)
        proximity = 1 - 0.5 * (d / c.radius_m) if (c.radius_m and d is not None) else 0.5
        score = price(c, fmt) * max(0.1, proximity)
        if score > best_score:
            best, best_score = c, score
    return best


def _matches_cart(c: Campaign, items: list[OrderItem]) -> bool:
    cats = {x.lower() for x in (c.target_categories or [])}
    kws = [k.lower() for k in (c.sku_keywords or [])]
    if not cats and not kws:
        return True
    for it in items:
        name = it.name.lower()
        if it.category and it.category.lower() in cats and (not kws or any(k in name or k == (it.brand or "") for k in kws)):
            return True
        if not cats and any(k in name or k == (it.brand or "") for k in kws):
            return True
    return False


def pick_subvention(db: Session, m: Merchant, items: list[OrderItem], deficit: int) -> list[Campaign]:
    if deficit <= 0:
        return []
    cands = [c for c in db.scalars(select(Campaign).where(Campaign.kind == "subvention", Campaign.status == "active"))
             if _matches_cart(c, items) and _base_eligible(db, c, m)]
    cands.sort(key=lambda c: c.bid_paise, reverse=True)
    chosen, covered = [], 0
    for c in cands:
        if covered >= deficit or len(chosen) >= MAX_SPONSORS:
            break
        chosen.append(c)
        covered += c.bid_paise
    return chosen


def idle_banners(db: Session, m: Merchant, limit: int = 5) -> list[dict]:
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.kind == "audio", Campaign.status == "active")):
        if c.creative and _in_geofence(c, m) and c.advertiser.category not in (m.blocked_categories or []) \
                and not (c.advertiser.type == "local" and c.advertiser.category == m.category):
            out.append(c.creative.banner)
    return out[:limit]


def cacheable_audio(db: Session, m: Merchant) -> list[tuple[str, int]]:
    """(audio_hash, duration_ms) of creatives that could play at this merchant."""
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.kind == "audio", Campaign.status == "active")):
        if c.creative and c.creative.audio_hash and _in_geofence(c, m):
            out.append((c.creative.audio_hash, c.creative.duration_ms or 0))
    return out
