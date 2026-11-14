"""Merchant ad-earnings tracker: what the Soundbox ads earned, after paying the Soundbox rental."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Hold, LedgerEntry, Merchant, Order
from .settlement import IST, RENTAL_ACCOUNT, earnings_account, rental_due, rental_paid


def _ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def summary(db: Session, m: Merchant) -> dict:
    """Small block for the merchant header / stats."""
    acct = earnings_account(m.id)
    lifetime = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0))
                          .where(LedgerEntry.account == acct)).scalar_one()
    paid = rental_paid(db, m.id)
    plays = db.scalars(select(Hold.amount_paise).join(Order, Hold.order_id == Order.id).where(
        Order.merchant_id == m.id, Hold.kind == "audio", Hold.status == "committed")
        .order_by(Hold.created_at.desc()).limit(200)).all()
    per_play = round(sum(plays) / len(plays)) if plays else None
    to_merchant = per_play * (1 - settings.platform_surplus_take_pct / 100) if per_play else None
    due = rental_due(db, m)
    return {
        "earnings_lifetime_paise": lifetime,
        "ad_income_per_play_paise": per_play,
        "platform_share_pct": settings.platform_surplus_take_pct,
        "rental": {"monthly_fee_paise": m.monthly_rental_paise, "paid_this_month_paise": min(paid, m.monthly_rental_paise),
                   "due_paise": due,
                   # verified plays still needed to clear this month's rental
                   "plays_to_cover": (math.ceil(due / to_merchant) if due and to_merchant else (0 if not due else None))},
    }


def tracker(db: Session, m: Merchant, days: int = 30) -> dict:
    """Full earnings page: totals, daily series, by advertiser, recent bills."""
    now = datetime.now(IST)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0, month0 = today0 - timedelta(days=6), today0.replace(day=1)
    since = today0 - timedelta(days=days - 1)

    acct = earnings_account(m.id)
    earn_rows = db.execute(select(LedgerEntry.amount_paise, LedgerEntry.ts)
                           .where(LedgerEntry.account == acct, LedgerEntry.amount_paise > 0)).all()
    rental_rows = db.execute(select(LedgerEntry.amount_paise, LedgerEntry.ts).where(
        LedgerEntry.account == RENTAL_ACCOUNT, LedgerEntry.ref.like(f"rental:{m.id}:%"),
        LedgerEntry.amount_paise > 0)).all()
    holds = db.execute(select(Hold.amount_paise, Hold.kind, Hold.resolved_at, Hold.advertiser_id, Hold.order_id)
                       .join(Order, Hold.order_id == Order.id)
                       .where(Order.merchant_id == m.id, Hold.kind.in_(("audio", "tag")),
                              Hold.status == "committed")).all()

    def total(rows, start):
        return sum(a for a, ts in rows if ts and _ist(ts) >= start)

    daily: dict[str, dict] = {}
    for i in range(days):
        d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "earnings_paise": 0, "rental_paise": 0, "plays": 0}
    for a, ts in earn_rows:
        k = _ist(ts).strftime("%Y-%m-%d")
        if k in daily:
            daily[k]["earnings_paise"] += a
    for a, ts in rental_rows:
        k = _ist(ts).strftime("%Y-%m-%d")
        if k in daily:
            daily[k]["rental_paise"] += a
    by_adv: dict[str, dict] = defaultdict(lambda: {"plays": 0, "tags": 0, "ad_revenue_paise": 0})
    for amount, kind, ts, adv_id, _ in holds:
        if ts:
            k = _ist(ts).strftime("%Y-%m-%d")
            if k in daily:
                daily[k]["plays"] += 1
        b = by_adv[adv_id]
        b["plays" if kind == "audio" else "tags"] += 1
        b["ad_revenue_paise"] += amount

    from .models import Advertiser
    names = {a.id: a.name for a in db.scalars(select(Advertiser).where(Advertiser.id.in_(list(by_adv))))} if by_adv else {}
    recent = []
    for o in db.scalars(select(Order).where(Order.merchant_id == m.id, Order.status == "settled")
                        .order_by(Order.settled_at.desc()).limit(25)):
        s = o.settlement or {}
        if s.get("ad_revenue_paise"):
            ads = [x["name"] for x in s.get("sponsors", []) if x.get("status") == "committed"]
            recent.append({"order_id": o.id, "settled_at": o.settled_at, "bill_paise": o.total_paise,
                           "advertisers": ads, "ad_revenue_paise": s.get("ad_revenue_paise", 0),
                           "rental_paid_paise": s.get("rental_paid_paise", 0),
                           "earnings_paise": s.get("earnings_paise", 0)})

    return {
        **summary(db, m),
        "totals": {
            "today_paise": total(earn_rows, today0),
            "week_paise": total(earn_rows, week0),
            "month_paise": total(earn_rows, month0),
            "lifetime_paise": sum(a for a, _ in earn_rows),
            "rental_paid_lifetime_paise": sum(a for a, _ in rental_rows),
            "ad_revenue_lifetime_paise": sum(h[0] for h in holds),
            "plays_month": sum(1 for h in holds if h[2] and _ist(h[2]) >= month0),
            "plays_lifetime": len(holds),
        },
        "daily": list(daily.values()),
        "by_advertiser": sorted(({"advertiser_id": k, "name": names.get(k, k), **v} for k, v in by_adv.items()),
                                key=lambda x: -x["ad_revenue_paise"]),
        "recent": recent,
    }
