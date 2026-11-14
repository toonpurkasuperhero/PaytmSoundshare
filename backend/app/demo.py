"""Demo accounts for showing the product: created on request, removable in one command.

    python -m app.cli seed-demo      # create (idempotent: skips accounts that exist)
    python -m app.cli remove-demo    # delete every demo account and everything it touched

Accounts go through the same code paths as real users (validation, AI HSN/SAC
classification, AI ad copy + Gemini voice). Advertiser wallets get a ledger credit
explicitly labelled "Demo credit (not a real payment)".
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, or_, select

from . import auth, creative, factorizer, ledger
from .db import session_scope
from .models import (Advertiser, AuthSession, Campaign, CatalogItem, Claim, Creative, Device, Hold, LedgerEntry,
                     Leg, Merchant, Order, OrderItem, TopUp, User)
from .money import inr, new_id

log = logging.getLogger("zeromdr.demo")
DEMO_PASSWORD = "Demo@2026"
DEMO_CREDIT_REF = "topup:demo-credit"

MERCHANTS = [
    {"phone": "9000000101", "name": "Sharma Electronics", "category": "electronics", "gstin": "29ABCDE1234F1Z5",
     "vpa": "sharma.electronics@okicici", "lat": 12.9716, "lng": 77.5946, "lang": "en",
     "address": "MG Road, Bengaluru", "device": "Counter 1",
     "catalog": [("Havells Mixer Grinder 750W", 470000), ("Extended Warranty & Installation", 180000),
                 ("Bajaj Ceiling Fan 1200mm", 240000), ("Prestige Induction Cooktop", 260000),
                 ("Philips LED Bulb 9W", 12000), ("Havells Electric Kettle 1.5L", 160000),
                 ("Home Delivery", 15000),
                 ("LG 32-inch HD Ready LED TV", 1599000), ("Samsung 253L Double Door Refrigerator", 2649000),
                 ("Voltas 1.5 Ton 3 Star Split AC", 3499000), ("IFB 6kg Front Load Washing Machine", 2799000),
                 ("Crompton 15L Storage Water Heater", 749900), ("Bajaj 20L Microwave Oven", 699000),
                 ("Usha Dry Iron 1000W", 129900), ("Havells Room Heater 2000W", 249900),
                 ("Orient 50L Desert Air Cooler", 899000), ("Syska 10000mAh Power Bank", 119900),
                 ("boAt Wireless Earbuds", 149900), ("Philips Hair Trimmer", 189900),
                 ("HDMI Cable 1.5m", 29900), ("Wipro 5-Socket Extension Board", 49900),
                 ("TV Wall Mounting Service", 49900), ("AC Installation Service", 150000),
                 ("AC Annual Maintenance Contract", 249900), ("Washing Machine Repair Visit", 39900),
                 ("TV Extended Warranty 2 Years", 199900)]},
    {"phone": "9000000102", "name": "Annapurna Bakery", "category": "bakery", "gstin": "29PQRSX5678K1Z2",
     "vpa": "annapurna.bakery@okaxis", "lat": 12.9722, "lng": 77.5961, "lang": "hi",
     "address": "Brigade Road, Bengaluru", "device": "Billing counter",
     "catalog": [("Black Forest Cake 1kg", 90000), ("Butter Cookies 500g", 32000),
                 ("Custom Cake Design Service", 60000),
                 ("Chocolate Truffle Cake 500g", 55000), ("Pineapple Pastry", 6000), ("Veg Puff", 2500),
                 ("Paneer Puff", 3500), ("Whole Wheat Bread 400g", 5000), ("Butter Croissant", 6000),
                 ("Assorted Cupcakes Box of 6", 24000), ("Plum Cake 500g", 32000), ("Khari Biscuit 200g", 9000),
                 ("Rusk 300g", 7000), ("Birthday Candles Pack", 3000), ("Cold Coffee 300ml", 9000),
                 ("Masala Chai", 2000), ("Home Delivery", 4000), ("Party Catering Service (per plate)", 25000)]},
]
ADVERTISERS = [
    {"phone": "9000000201", "name": "FitZone Gym", "type": "local", "category": "fitness",
     "lat": 12.9733, "lng": 77.5958, "address": "Residency Road, Bengaluru", "credit": 30000,
     "campaign": {"kind": "audio", "name": "Annual membership promo",
                  "prompt": "1 month free on annual membership, this week only", "lang": "en",
                  "radius_m": 500, "bid_paise": 120, "daily_cap_paise": 5000}},
    {"phone": "9000000202", "name": "Dr. Smile Dental", "type": "local", "category": "healthcare",
     "lat": 12.9699, "lng": 77.5930, "address": "Church Street, Bengaluru", "credit": 20000,
     "campaign": {"kind": "audio", "name": "Free check-up week",
                  "prompt": "Free dental check-up this week", "lang": "hi",
                  "radius_m": 400, "bid_paise": 90, "daily_cap_paise": 3000}},
    {"phone": "9000000203", "name": "Havells", "type": "brand", "category": "appliance",
     "lat": None, "lng": None, "address": None, "credit": 1000000,
     "campaign": {"kind": "subvention", "name": "Appliance clearing rights",
                  "prompt": "Havells pays the payment fee when you buy a Havells appliance", "lang": "en",
                  "radius_m": 0, "bid_paise": 10500, "daily_cap_paise": 0,
                  "target_categories": ["appliance"], "sku_keywords": ["havells"]}},
]
DEMO_PHONES = [m["phone"] for m in MERCHANTS] + [a["phone"] for a in ADVERTISERS]


def _user(db, phone: str) -> User | None:
    return db.scalars(select(User).where(User.phone == phone)).first()


def seed() -> list[dict]:
    """Create the demo accounts. Returns a summary per account (including the Soundbox token once)."""
    out: list[dict] = []
    for spec in MERCHANTS:
        with session_scope() as db:
            u = _user(db, spec["phone"])
            if u:
                have = {c.name for c in db.scalars(select(CatalogItem).where(CatalogItem.merchant_id == u.merchant_id))}
                missing = [{"name": n, "unit_price": p, "qty": 1} for n, p in spec["catalog"] if n not in have]
                note = "no new catalog items"
                if missing:
                    classified, source, reason = factorizer.classify(missing)
                    for c in classified:
                        db.add(CatalogItem(id=new_id("C", 4), merchant_id=u.merchant_id, name=c["name"],
                                           unit_price=c["unit_price"], hsn_sac=c["hsn_sac"], category=c["category"],
                                           brand=c.get("brand"),
                                           source={"ai": "ai", "fallback": "fallback"}.get(source, "manual")))
                    note = f"added {len(classified)} catalog items, classified by {source}" + (f" ({reason})" if reason else "")
                out.append({"role": "merchant", "name": spec["name"], "phone": spec["phone"], "status": "exists",
                            "catalog": note})
                continue
            m = Merchant(id=new_id("M", 4), name=spec["name"], category=spec["category"], gstin=spec["gstin"],
                         vpa=spec["vpa"], lat=spec["lat"], lng=spec["lng"], lang=spec["lang"],
                         address=spec["address"], blocked_categories=[])
            db.add(m)
            db.flush()
            db.add(User(id=new_id("U", 5), phone=spec["phone"], password_hash=auth.hash_password(DEMO_PASSWORD),
                        role="merchant", name=m.name, merchant_id=m.id))
            # Catalog: one batched AI classification call for the whole list.
            items = [{"name": n, "unit_price": p, "qty": 1} for n, p in spec["catalog"]]
            classified, source, reason = factorizer.classify(items)
            for c in classified:
                db.add(CatalogItem(id=new_id("C", 4), merchant_id=m.id, name=c["name"], unit_price=c["unit_price"],
                                   hsn_sac=c["hsn_sac"], category=c["category"], brand=c.get("brand"),
                                   source={"ai": "ai", "fallback": "fallback"}.get(source, "manual")))
            import secrets
            token = secrets.token_urlsafe(18)
            did = f"SB-{secrets.token_hex(2).upper()}"
            db.add(Device(id=did, merchant_id=m.id, name=spec["device"], token_hash=auth.sha256(token)))
            out.append({"role": "merchant", "name": m.name, "phone": spec["phone"], "status": "created",
                        "catalog": f"{len(classified)} items, classified by {source}"
                                   + (f" ({reason})" if reason else ""),
                        "device_id": did, "device_token": token})

    for spec in ADVERTISERS:
        with session_scope() as db:
            if _user(db, spec["phone"]):
                out.append({"role": "advertiser", "name": spec["name"], "phone": spec["phone"], "status": "exists"})
                continue
            a = Advertiser(id=new_id("A", 4), name=spec["name"], type=spec["type"], category=spec["category"],
                           lat=spec["lat"], lng=spec["lng"], address=spec["address"])
            db.add(a)
            db.flush()
            db.add(User(id=new_id("U", 5), phone=spec["phone"], password_hash=auth.hash_password(DEMO_PASSWORD),
                        role="advertiser", name=a.name, advertiser_id=a.id))
            ledger.post(db, DEMO_CREDIT_REF, "Demo credit (not a real payment)",
                        [("funding", -spec["credit"]), (f"adv:{a.id}", spec["credit"])])
            cs = dict(spec["campaign"])
            c = Campaign(id=new_id("CMP", 3), advertiser_id=a.id, status="generating", deploy_on_ready=True,
                         lat=a.lat, lng=a.lng, target_categories=cs.pop("target_categories", []),
                         sku_keywords=cs.pop("sku_keywords", []), **cs)
            db.add(c)
            cid, aname = c.id, a.name
        creative.generate(cid)  # synchronous: AI copy + Gemini voice
        with session_scope() as db:
            c = db.get(Campaign, cid)
            cr = c.creative
            out.append({"role": "advertiser", "name": aname, "phone": spec["phone"], "status": "created",
                        "wallet": inr(spec["credit"]) + " demo credit",
                        "campaign": f"{c.name}: {c.status}" + (f" ({c.error})" if c.error else ""),
                        "ad": (f"\"{cr.script}\" · copy={cr.source}" + (f", voice={cr.voice_source}" if cr.voice_source else "")
                               + (f" · {cr.duration_ms / 1000:.1f}s" if cr.duration_ms else "")) if cr else None})
    return out


def remove() -> dict:
    """Delete every demo account and all rows that belong to it, keeping the ledger balanced
    (whole transactions are removed, never single postings)."""
    with session_scope() as db:
        users = db.scalars(select(User).where(User.phone.in_(DEMO_PHONES))).all()
        mids = [u.merchant_id for u in users if u.merchant_id]
        aids = [u.advertiser_id for u in users if u.advertiser_id]
        oids = list(db.scalars(select(Order.id).where(Order.merchant_id.in_(mids)))) if mids else []
        cids = list(db.scalars(select(Campaign.id).where(Campaign.advertiser_id.in_(aids)))) if aids else []
        crids = list(db.scalars(select(Creative.id).where(Creative.campaign_id.in_(cids)))) if cids else []
        hold_orders = set(db.scalars(select(Hold.order_id).where(Hold.advertiser_id.in_(aids)))) if aids else set()
        foreign = sorted(hold_orders - set(oids))
        if foreign:
            raise RuntimeError(
                f"Demo advertisers sponsored {len(foreign)} order(s) of real merchants (e.g. {foreign[0]}). "
                "Removing them would rewrite real ledger history, so nothing was deleted. "
                "Pause the demo campaigns instead.")
        accounts = [f"merchant:{m}" for m in mids] + [f"adv:{a}" for a in aids]
        refs = [f"order:{o}" for o in oids]
        rental_refs = [f"rental:{m}:%" for m in mids]
        txn_q = select(LedgerEntry.txn_id).where(or_(LedgerEntry.account.in_(accounts), LedgerEntry.ref.in_(refs),
                                                     *[LedgerEntry.ref.like(r) for r in rental_refs]))
        txns = set(db.scalars(txn_q)) if (accounts or refs) else set()
        if txns:
            shared_in = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
                LedgerEntry.txn_id.in_(txns), LedgerEntry.account == "shared_pool")).scalar_one()
            shared_now = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
                LedgerEntry.account == "shared_pool")).scalar_one()
            if shared_now - shared_in < 0:
                raise RuntimeError("Demo shops' ad surplus has already paid real merchants' fees from the shared "
                                   "pool; removing them would leave the pool negative, so nothing was deleted.")
        counts = {"users": len(users), "merchants": len(mids), "advertisers": len(aids), "orders": len(oids),
                  "campaigns": len(cids), "ledger_txns": len(txns)}
        if txns:
            db.execute(delete(LedgerEntry).where(LedgerEntry.txn_id.in_(txns)))
        if crids:
            db.execute(delete(Claim).where(Claim.creative_id.in_(crids)))
        db.execute(delete(Hold).where(or_(Hold.advertiser_id.in_(aids), Hold.order_id.in_(oids))))
        if crids:
            db.execute(delete(Creative).where(Creative.id.in_(crids)))
        if cids:
            db.execute(delete(Campaign).where(Campaign.id.in_(cids)))
        if aids:
            db.execute(delete(TopUp).where(TopUp.advertiser_id.in_(aids)))
        if oids:
            db.execute(delete(Leg).where(Leg.order_id.in_(oids)))
            db.execute(delete(OrderItem).where(OrderItem.order_id.in_(oids)))
            db.execute(delete(Order).where(Order.id.in_(oids)))
        if mids:
            db.execute(delete(Device).where(Device.merchant_id.in_(mids)))
            db.execute(delete(CatalogItem).where(CatalogItem.merchant_id.in_(mids)))
        uids = [u.id for u in users]
        if uids:
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(uids)))
            db.execute(delete(User).where(User.id.in_(uids)))
        if mids:
            db.execute(delete(Merchant).where(Merchant.id.in_(mids)))
        if aids:
            db.execute(delete(Advertiser).where(Advertiser.id.in_(aids)))
    return counts
