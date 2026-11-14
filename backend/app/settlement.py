"""SoundShare settlement engine: the order lifecycle from bill to balanced ledger.

    create_order -> (leg QR shown) -> confirm_leg x N -> begin_settlement
      -> payment_success on device -> play_ack / timeout -> finalize

All money movement happens under `money_lock` inside one DB transaction, and
device messages are sent only after the commit.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import adx, announcer, factorizer, ledger, mdr, sentinel, tags
from .config import settings
from .db import money_lock, session_scope
from .hub import device_url, hub, public_url
from .models import Campaign, Device, Hold, LedgerEntry, Leg, Merchant, Order, OrderItem, TopUp, utcnow
from .money import announce_tokens, new_id, order_id
from .payments import PaymentStatus, ProviderError, get_provider, provider_by_name

log = logging.getLogger("zeromdr.settlement")

LATENCIES_MS: deque[float] = deque(maxlen=500)


# SoundShare money flow for each settled sale (see _finalize):
#   ad money -> this sale's fee -> platform cut -> this merchant's Soundbox rental -> SHARED_POOL
#   SHARED_POOL -> other merchants' fee shortfalls (daily cap each) -> their rentals (above a fee reserve)
SHARED_POOL = "shared_pool"
RENTAL_ACCOUNT = "soundbox_rental"
IST = timezone(timedelta(hours=5, minutes=30))


def rental_ref(merchant_id: str, when: datetime | None = None) -> str:
    return f"rental:{merchant_id}:{(when or datetime.now(IST)).astimezone(IST):%Y-%m}"


def rental_paid(db: Session, merchant_id: str) -> int:
    return db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.ref == rental_ref(merchant_id), LedgerEntry.account == RENTAL_ACCOUNT)).scalar_one()


def rental_due(db: Session, merchant: Merchant) -> int:
    return max(0, merchant.monthly_rental_paise - rental_paid(db, merchant.id))


def _ist_day_start() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def shared_draw_left_today(db: Session, merchant_id: str) -> int:
    drawn = db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.account == f"merchant:{merchant_id}", LedgerEntry.memo == "MDR covered by the SoundShare pool",
        LedgerEntry.ts >= _ist_day_start())).scalar_one()
    return max(0, settings.shared_pool_daily_cap_paise - drawn)
MIN_PLAY_FRACTION = 0.8
MIC_NOISE_FLOOR_DB = -50.0


class SentinelBlocked(Exception):
    def __init__(self, verdict: dict):
        super().__init__("sentinel_blocked")
        self.verdict = verdict


@dataclass
class Outbox:
    """Device messages collected during a transaction, sent after commit."""
    device_id: str | None = None
    msgs: list[dict] = field(default_factory=list)
    events: list[tuple[str, dict]] = field(default_factory=list)
    t0: float | None = None

    def flush(self) -> None:
        for m in self.msgs:
            hub.send_device(self.device_id, m)
            if m["type"] == "payment_success" and self.t0 is not None:
                LATENCIES_MS.append((time.perf_counter() - self.t0) * 1000)
        for name, data in self.events:
            hub.emit(name, **data)


# ------------------------------------------------------------------ helpers

def _ts(dt) -> int | None:
    return int(dt.timestamp()) if dt else None


def bill_messages(order: Order) -> list[dict]:
    msgs = [{"type": "show_bill", "orderId": order.id,
             "items": [{"name": i.name, "qty": i.qty, "amount": i.amount_paise} for i in order.items],
             "total": order.total_paise}]
    if len(order.legs) > 1:
        msgs.append({"type": "show_split", "orderId": order.id, "total": order.total_paise,
                     "legs": [{"seq": l.seq, "label": l.label, "amount": l.amount_paise} for l in order.legs],
                     "note": "Separate GST invoices. Fee is calculated after payment."})
    active = next((l for l in order.legs if l.status == "active"), None)
    if active:
        msgs.append(qr_message(order, active))
    return msgs


def qr_message(order: Order, leg: Leg) -> dict:
    return {"type": "show_qr", "orderId": order.id, "legId": leg.id, "seq": leg.seq, "of": leg.of,
            "qrData": leg.qr_data or leg.qr_image_url, "amount": leg.amount_paise,
            "expiresAt": _ts(leg.expires_at)}


def _activate_leg(db: Session, order: Order, leg: Leg, merchant: Merchant) -> None:
    provider = get_provider()
    expires = utcnow() + timedelta(minutes=settings.qr_expiry_min)
    created = provider.create_payment(
        ref=leg.id, amount_paise=leg.amount_paise,
        description=f"{merchant.name} {order.id} {leg.seq}/{leg.of} {leg.label}",
        expires_at=expires, pos_id=order.device_id or "POS1",
    )
    leg.provider = provider.name
    leg.provider_ref = created.provider_ref
    leg.qr_data = created.qr_data
    leg.qr_image_url = created.qr_image_url
    leg.checkout_url = created.checkout_url
    leg.expires_at = expires
    leg.status = "active"


# ------------------------------------------------------------------ orders

def create_order(db: Session, merchant_id: str, items_in: list[dict], device_id: str | None,
                 factorize: bool | None, legs_in: list | None = None, plan_source: str | None = None,
                 rationale: str | None = None, fallback_reason: str | None = None,
                 model: str | None = None) -> tuple[Order, Outbox]:
    """legs_in: item-index groups from a reviewed plan ([[1],[0]] or [{"item_indexes":[1],"reason":..}]).
    Without legs_in the bill is planned now (AI classification + AI division)."""
    from . import planner

    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise LookupError("merchant not found")
    if device_id:
        dev = db.get(Device, device_id)
        if not dev or dev.merchant_id != merchant.id:
            raise LookupError("device not found for this merchant")
    elif merchant.devices:
        device_id = merchant.devices[0].id
    if not items_in or sum(int(i.get("qty") or 1) * int(i.get("unit_price") or 0) for i in items_in) <= 0:
        raise ValueError("bill must have at least one item with a positive amount")
    fz = merchant.factorization_enabled if factorize is None else factorize

    if legs_in:
        classified, _, _ = factorizer.classify(planner.apply_catalog(db, merchant, items_in))
        items = factorizer.normalize(classified, merchant.gstin)
        groups = [l["item_indexes"] if isinstance(l, dict) else l for l in legs_in]
        reasons = [str(l.get("reason") or "") if isinstance(l, dict) else "" for l in legs_in]
        plans = factorizer.legs_from_indexes(items, groups, reasons)
        division = {"source": plan_source or "manual", "fallback_reason": fallback_reason,
                    "rationale": rationale, "model": model if plan_source == "ai" else None}
    else:
        plan, items, plans = planner.build(db, merchant, items_in, fz)
        division = {k: plan[k] for k in ("source", "fallback_reason", "rationale", "model")}
    total = sum(i.amount for i in items)
    oid = order_id()
    verdict = sentinel.check_plan(db, merchant, items, plans, custom=True, ref=f"order:{oid}")
    if verdict["decision"] == "block":
        db.commit()  # persist the flags
        hub.emit("sentinel_flag", ref=f"order:{oid}", decision="block")
        raise SentinelBlocked(verdict)

    order = Order(id=oid, merchant_id=merchant.id, device_id=device_id, status="created",
                  total_paise=total, factorize=fz, sentinel=verdict, division=division)
    db.add(order)
    rows = []
    for it in items:
        row = OrderItem(order_id=oid, idx=it.idx, name=it.name, qty=it.qty, unit_price=it.unit_price,
                        amount_paise=it.amount, hsn_sac=it.hsn_sac, supply_type=it.supply_type,
                        category=it.category, brand=it.brand, supplier_gstin=it.supplier_gstin,
                        classification_source=it.source)
        db.add(row)
        rows.append(row)
    db.flush()
    for seq, lp in enumerate(plans, start=1):
        db.add(Leg(id=new_id("L", 5), order_id=oid, seq=seq, of=len(plans), label=lp.label, reason=lp.reason or None,
                   supply_type=lp.supply_type, supplier_gstin=lp.supplier_gstin, amount_paise=lp.amount,
                   item_ids=[rows[i].id for i in lp.item_idx], status="pending"))
    db.flush()
    db.refresh(order)
    try:
        _activate_leg(db, order, order.legs[0], merchant)
    except ProviderError:
        db.rollback()
        raise
    order.status = "awaiting_payment"
    ad_msg = _reserve_counter_ad(db, order, merchant)
    db.commit()
    db.refresh(order)
    announcer.prewarm(merchant.lang, total)  # the announcement is ready by the time the customer pays
    out = Outbox(device_id=device_id, msgs=bill_messages(order) + ([ad_msg] if ad_msg else []),
                 events=[("order_update", {"order_id": oid, "status": order.status})])
    return order, out


def _reserve_counter_ad(db: Session, order: Order, merchant: Merchant) -> dict | None:
    """Pick the counter ad as the QR goes up (the customer is at the counter, about to pay).

    Normal hours: a full ad, sent now so it plays WHILE the customer pays; the payment message
    waits for it. Charged only if it played fully AND the bill was then paid (customer present).
    Busy hour: only a short sponsor tag, played after the payment message, at the lower tag price.
    """
    if not order.device_id or adx.in_quiet_hours(merchant):
        return None
    fmt = "tag" if merchant.busy_mode else "ad"
    c = adx.pick_audio(db, merchant, order.device_id, fmt)
    if not c:
        return None
    cr = c.creative
    hold = Hold(id=new_id("P", 5), advertiser_id=c.advertiser_id, campaign_id=c.id, order_id=order.id,
                device_id=order.device_id, kind="audio" if fmt == "ad" else "tag",
                amount_paise=adx.price(c, fmt), duration_ms=cr.duration_ms if fmt == "ad" else None)
    db.add(hold)
    db.flush()
    if fmt == "tag":
        tags.prewarm(c.advertiser.name, merchant.lang)
        return None
    hold.sent_at = utcnow()
    return {"type": "play_ad", "orderId": order.id, "playId": hold.id,
            "ad": {"hash": cr.audio_hash, "url": device_url(order.device_id, f"/media/audio/{cr.audio_hash}.mp3"),
                   "durationMs": cr.duration_ms or 0, "advertiser": c.advertiser.name},
            "banner": cr.banner,
            "offerQr": public_url(order.device_id, f"/api/offers/{cr.id}/claim?d={order.device_id}")}


def _release_open_holds(db: Session, order_id_: str, reason: str) -> None:
    """Bill abandoned / failed: an ad played to a customer who didn't pay is not charged."""
    for h in db.scalars(select(Hold).where(Hold.order_id == order_id_, Hold.status == "reserved")):
        h.status, h.release_reason, h.resolved_at = "released", reason, utcnow()


def cancel_order(order_id_: str) -> None:
    refs = []
    with money_lock, session_scope() as db:
        order = db.get(Order, order_id_)
        if not order or order.status not in ("created", "awaiting_payment", "partially_paid"):
            return
        for l in order.legs:
            if l.status in ("pending", "active"):
                if l.status == "active" and l.provider and l.provider_ref:
                    refs.append((l.provider, l.provider_ref))
                l.status = "cancelled"
        order.status = "cancelled"
        _release_open_holds(db, order.id, "bill_cancelled")
        out = Outbox(order.device_id, [{"type": "cancelled", "orderId": order.id}],
                     [("order_update", {"order_id": order.id, "status": "cancelled"})])
    out.flush()
    for prov, ref in refs:
        try:
            provider_by_name(prov).cancel(ref)
        except Exception as e:  # best effort
            log.info("cancel %s failed: %s", ref, e)


# ------------------------------------------------------------------ payment confirmation

def confirm_leg(leg_id: str, status: PaymentStatus) -> None:
    """Single entry point for webhook, poller and mock payments. Idempotent."""
    t0 = time.perf_counter()
    with money_lock, session_scope() as db:
        leg = db.get(Leg, leg_id)
        if not leg or leg.status not in ("active", "pending"):
            return
        order = db.get(Order, leg.order_id)
        merchant = db.get(Merchant, order.merchant_id)
        out = Outbox(device_id=order.device_id, t0=t0)

        if status.state in ("failed", "expired"):
            leg.status = status.state
            order.status = "failed"
            _release_open_holds(db, order.id, f"payment_{status.state}")
            out.msgs.append({"type": "payment_failed", "orderId": order.id, "legId": leg.id, "reason": status.state})
            out.events.append(("order_update", {"order_id": order.id, "status": "failed"}))
        elif status.state == "paid":
            _apply_leg_payment(db, order, leg, merchant, status, out)
        else:
            return
    out.flush()


def _apply_leg_payment(db: Session, order: Order, leg: Leg, merchant: Merchant,
                       status: PaymentStatus, out: Outbox) -> None:
    leg.status = "paid"
    leg.rail = status.rail or "UNKNOWN"
    leg.payer_ref = status.payer_ref
    leg.provider_txn_id = status.txn_id
    leg.payment_mode_raw = status.raw or None
    leg.paid_at = utcnow()
    leg.mdr_paise = mdr.mdr_total(leg.amount_paise, leg.rail)
    ref = f"order:{order.id}"
    ledger.post(db, ref, f"Leg {leg.seq}/{leg.of} {leg.label} paid via {leg.rail}", [
        ("customer", -leg.amount_paise),
        (f"merchant:{merchant.id}", leg.amount_paise - leg.mdr_paise),
        ("acquirer", leg.mdr_paise),
    ])
    verdict = sentinel.check_payment(db, merchant, leg)
    if verdict["deny_subsidy"]:
        order.sentinel = {**(order.sentinel or {}), "deny_subsidy": True,
                          "post_payment": verdict["reasons"]}
        out.events.append(("sentinel_flag", {"ref": ref, "decision": "deny_subsidy"}))
    out.msgs.append({"type": "leg_paid", "orderId": order.id, "legId": leg.id, "seq": leg.seq,
                     "of": leg.of, "amount": leg.amount_paise, "rail": leg.rail})

    nxt = next((l for l in order.legs if l.status == "pending"), None)
    if nxt:
        _activate_leg(db, order, nxt, merchant)
        order.status = "partially_paid"
        out.msgs.append(qr_message(order, nxt))
        out.events.append(("order_update", {"order_id": order.id, "status": order.status}))
        return
    order.status = "paid"
    order.paid_at = utcnow()
    _begin_settlement(db, order, merchant, out)


def _commit_hold(db: Session, hold: Hold, memo: str) -> None:
    hold.status = "committed"
    hold.resolved_at = utcnow()
    ledger.post(db, f"order:{hold.order_id}", memo, [
        (f"adv:{hold.advertiser_id}", -hold.amount_paise), ("sponsor_pool", hold.amount_paise)])


def _begin_settlement(db: Session, order: Order, merchant: Merchant, out: Outbox) -> None:
    legs = order.legs
    mdr_due = sum(l.mdr_paise or 0 for l in legs)
    biggest = max(legs, key=lambda l: l.amount_paise)
    mdr_unsplit = mdr.mdr_total(order.total_paise, biggest.rail) if len(legs) > 1 else mdr_due
    deny = bool((order.sentinel or {}).get("deny_subsidy"))

    expected = 0
    counter = db.scalars(select(Hold).where(Hold.order_id == order.id, Hold.kind.in_(("audio", "tag")),
                                            Hold.status == "reserved")).first()
    audio_c: Campaign | None = counter.campaign if counter else None
    tag_clip = None
    if counter and deny:  # no ad money from self-payments
        counter.status, counter.release_reason, counter.resolved_at = "released", "self_dealing", utcnow()
        counter, audio_c = None, None
    elif counter and counter.kind == "audio":
        if counter.verified:  # played fully while the customer paid -> charge now
            _commit_hold(db, counter, f"Verified ad play during payment: {audio_c.advertiser.name}")
        elif not counter.sent_at:  # device was offline when the QR went up: nothing played
            counter.status, counter.release_reason, counter.resolved_at = "released", "not_played", utcnow()
            counter, audio_c = None, None
        # else: still playing -> its play_ack settles it, then the payment message plays
    elif counter and counter.kind == "tag":
        try:
            h_, dur = tags.ensure(audio_c.advertiser.name, merchant.lang)
            counter.duration_ms, counter.sent_at = dur, utcnow()
            tag_clip = {"hash": h_, "url": device_url(order.device_id, f"/media/audio/{h_}.mp3"), "durationMs": dur,
                        "advertiser": audio_c.advertiser.name, "kind": "tag"}
        except Exception as e:  # no voice for the tag: don't charge for a tag that can't play
            log.warning("sponsor tag unavailable: %s", e)
            counter.status, counter.release_reason, counter.resolved_at = "released", "tag_unavailable", utcnow()
            counter, audio_c = None, None
    if counter:
        expected += counter.amount_paise

    sponsors = [] if deny else adx.pick_subvention(db, merchant, order.items, mdr_due - expected)
    for c in sponsors:
        h = Hold(id=new_id("P", 5), advertiser_id=c.advertiser_id, campaign_id=c.id, order_id=order.id,
                 device_id=order.device_id, kind="subvention", amount_paise=c.bid_paise)
        db.add(h)
        db.flush()
        _commit_hold(db, h, f"Brand subvention: {c.advertiser.name}")
        expected += c.bid_paise

    pool_bal = 0 if deny else max(0, min(ledger.balance(db, SHARED_POOL), shared_draw_left_today(db, merchant.id)))
    covered_expected = min(mdr_due, expected + pool_bal)
    order.settlement = {
        "mdr_paise": mdr_due, "mdr_unsplit_paise": mdr_unsplit,
        "saved_by_factorization_paise": max(0, mdr_unsplit - mdr_due),
        "status": "pending_ack",
    }
    covered_by = ([{"name": c.advertiser.name, "amount": c.bid_paise} for c in sponsors]
                  + ([{"name": audio_c.advertiser.name, "amount": counter.amount_paise}] if counter else []))
    tokens, text = announce_tokens(order.total_paise, merchant.lang)
    lang_ = merchant.lang if merchant.lang in ("en", "hi") else "en"  # local clip packs: en/hi
    msg = {
        "type": "payment_success", "orderId": order.id, "amount": order.total_paise, "lang": merchant.lang,
        "announce": tokens if lang_ == merchant.lang else announce_tokens(order.total_paise, lang_)[0],
        "announceText": text,
        "announceUrl": (device_url(order.device_id, f"/api/announce/{order.id}.mp3")
                        if announcer.available(merchant.lang) else None), "playId": None, "ad": None, "banner": None, "offerQr": None,
        "settlement": {
            "mdr": mdr_due, "merchantReceives": order.total_paise - mdr_due + covered_expected,
            "coveragePct": round(100.0 * covered_expected / mdr_due, 1) if mdr_due else 100.0,
            "coveredBy": covered_by,
        },
    }
    if audio_c:
        cr = audio_c.creative
        msg["banner"] = cr.banner
        msg["offerQr"] = public_url(order.device_id, f"/api/offers/{cr.id}/claim?d={order.device_id or ''}")
        if tag_clip:  # busy hour: the sponsor tag plays right after the payment message
            msg["playId"], msg["ad"] = counter.id, tag_clip
        # normal hours: the full ad already played (or is finishing) while the customer paid
    elif sponsors:
        b = sponsors[0].creative.banner if sponsors[0].creative else None
        msg["banner"] = b
    out.msgs.append(msg)
    out.events.append(("order_update", {"order_id": order.id, "status": "paid"}))

    if not counter or counter.status != "reserved":
        _finalize(db, order, out)


def _finalize(db: Session, order: Order, out: Outbox) -> None:
    holds = db.scalars(select(Hold).where(Hold.order_id == order.id)).all()
    if any(h.status == "reserved" for h in holds):
        return
    s = dict(order.settlement or {})
    mdr_due = s.get("mdr_paise", 0)
    funds = sum(h.amount_paise for h in holds if h.status == "committed")
    ref = f"order:{order.id}"
    merchant = db.get(Merchant, order.merchant_id)
    merchant_acct = f"merchant:{merchant.id}"
    deny = bool((order.sentinel or {}).get("deny_subsidy"))

    # 1. This sale's ad money covers this sale's fee first.
    covered_ads = min(mdr_due, funds)
    ledger.post(db, ref, "MDR rebate to merchant (sponsor-funded)",
                [("sponsor_pool", -covered_ads), (merchant_acct, covered_ads)])
    # 2. Shortfall: the shared SoundShare pool (other merchants' surplus), within a daily cap.
    drawn = 0
    if mdr_due > covered_ads and not deny:
        drawn = min(mdr_due - covered_ads, max(0, ledger.balance(db, SHARED_POOL)),
                    shared_draw_left_today(db, merchant.id))
        ledger.post(db, ref, "MDR covered by the SoundShare pool", [(SHARED_POOL, -drawn), (merchant_acct, drawn)])
    # 3. Surplus: platform cut -> this merchant's Soundbox rental for the month -> shared pool.
    surplus = funds - covered_ads
    spread = round(surplus * settings.platform_surplus_take_pct / 100)
    ledger.post(db, ref, "Platform spread", [("sponsor_pool", -spread), ("platform", spread)])
    rest = surplus - spread
    rental = min(rest, rental_due(db, merchant)) if not deny else 0
    ledger.post(db, rental_ref(merchant.id), f"Soundbox rental paid by ads ({order.id})",
                [("sponsor_pool", -rental), (RENTAL_ACCOUNT, rental)])
    shared = rest - rental
    ledger.post(db, ref, "Ad surplus shared with the SoundShare pool", [("sponsor_pool", -shared), (SHARED_POOL, shared)])
    # 4. Shared pool also pays this merchant's unpaid rental, keeping a reserve for fees first.
    rental_from_pool = 0
    if not deny and rental_due(db, merchant) > 0:
        spare = ledger.balance(db, SHARED_POOL) - settings.shared_pool_fee_reserve_paise
        rental_from_pool = max(0, min(spare, rental_due(db, merchant)))
        ledger.post(db, rental_ref(merchant.id), f"Soundbox rental paid by the SoundShare pool ({order.id})",
                    [(SHARED_POOL, -rental_from_pool), (RENTAL_ACCOUNT, rental_from_pool)])
    covered = covered_ads + drawn
    s.update({
        "ad_liquidity_paise": funds, "covered_paise": covered,
        "covered_by_ads_paise": covered_ads, "shared_drawn_paise": drawn,
        "rental_paid_paise": rental + rental_from_pool, "rental_from_pool_paise": rental_from_pool,
        "shared_contributed_paise": shared, "shared_pool_balance_paise": ledger.balance(db, SHARED_POOL),
        "coverage_pct": round(100.0 * covered / mdr_due, 1) if mdr_due else 100.0,
        "merchant_receives_paise": order.total_paise - mdr_due + covered,
        "acquirer_paise": mdr_due, "platform_paise": spread,
        "sponsors": [{"advertiser_id": h.advertiser_id, "name": h.advertiser.name, "kind": h.kind,
                      "amount_paise": h.amount_paise, "status": h.status,
                      **({"release_reason": h.release_reason} if h.release_reason else {})} for h in holds],
        "status": "settled",
    })
    order.settlement = s
    order.status = "settled"
    order.settled_at = utcnow()
    out.events.append(("order_update", {"order_id": order.id, "status": "settled"}))


# ------------------------------------------------------------------ play verification

def play_ack(device_id: str, msg: dict) -> None:
    with money_lock, session_scope() as db:
        hold = db.get(Hold, str(msg.get("playId") or ""))
        if not hold or hold.status != "reserved" or (hold.device_id and hold.device_id != device_id):
            return
        ms = int(msg.get("ms") or 0)
        peak = msg.get("peakDb")
        hold.ack_ms = ms
        hold.peak_db = float(peak) if peak is not None else None
        need = int((hold.duration_ms or 0) * MIN_PLAY_FRACTION)
        ok = ms >= need and (peak is None or float(peak) > MIC_NOISE_FLOOR_DB)
        order = db.get(Order, hold.order_id)
        paid = order.status in ("paid", "settled")
        what = "sponsor tag" if hold.kind == "tag" else "ad play during payment"
        if not ok:
            hold.status, hold.release_reason, hold.resolved_at = "released", "play_not_verified", utcnow()
        elif paid:
            _commit_hold(db, hold, f"Verified {what}: {hold.advertiser.name} ({ms} ms)")
        else:
            # Played fully while the customer was still paying: charged only once they actually pay.
            hold.verified = True
        out = Outbox(order.device_id, events=[("play_ack", {"play_id": hold.id, "verified": ok, "ms": ms})])
        if paid:
            _finalize(db, order, out)
    out.flush()


def release_stale_holds() -> None:
    cutoff = utcnow() - timedelta(seconds=settings.play_ack_timeout_s)
    with money_lock, session_scope() as db:
        # Only plays actually sent to a device and never confirmed. A verified play waiting for the
        # customer's payment, or a sponsor tag not yet sent, is not stale.
        stale = db.scalars(select(Hold).where(Hold.status == "reserved", Hold.verified.is_(False),
                                              Hold.sent_at.is_not(None), Hold.sent_at < cutoff)).all()
        if not stale:
            return
        out = Outbox()
        for h in stale:
            h.status, h.release_reason, h.resolved_at = "released", "no_ack_timeout", utcnow()
        db.flush()
        for oid in {h.order_id for h in stale}:
            o = db.get(Order, oid)
            if o.status in ("paid", "settled"):
                _finalize(db, o, out)
    out.flush()


def expire_legs() -> None:
    now = utcnow()
    with session_scope() as db:
        ids = [l.id for l in db.scalars(select(Leg).where(Leg.status == "active", Leg.expires_at < now))]
    for lid in ids:
        confirm_leg(lid, PaymentStatus("expired"))


# ------------------------------------------------------------------ top-ups

def create_topup(db: Session, advertiser_id: str, amount_paise: int) -> TopUp:
    provider = get_provider()
    t = TopUp(id=new_id("T", 5), advertiser_id=advertiser_id, amount_paise=amount_paise,
              provider=provider.name, status="pending")
    db.add(t)
    db.flush()
    if provider.name == "mock":
        t.status = "paid"
        ledger.post(db, f"topup:{t.id}", "Advertiser wallet top-up",
                    [("funding", -amount_paise), (f"adv:{advertiser_id}", amount_paise)])
    else:
        created = provider.create_payment(ref=t.id, amount_paise=amount_paise,
                                          description=f"SoundShare ad wallet top-up {t.id}",
                                          expires_at=utcnow() + timedelta(minutes=30), pos_id="ADS")
        t.provider_ref, t.qr_data, t.checkout_url = created.provider_ref, created.qr_data, created.checkout_url
    db.commit()
    return t


def confirm_topup(topup_id: str, status: PaymentStatus) -> None:
    with money_lock, session_scope() as db:
        t = db.get(TopUp, topup_id)
        if not t or t.status != "pending":
            return
        if status.state == "paid":
            t.status = "paid"
            ledger.post(db, f"topup:{t.id}", "Advertiser wallet top-up",
                        [("funding", -t.amount_paise), (f"adv:{t.advertiser_id}", t.amount_paise)])
        elif status.state in ("failed", "expired"):
            t.status = "failed"


# ------------------------------------------------------------------ provider polling

def poll_once() -> None:
    """Poll non-mock providers for pending legs / top-ups (works without public webhooks)."""
    with session_scope() as db:
        legs = [(l.id, l.provider, l.provider_ref) for l in db.scalars(
            select(Leg).where(Leg.status == "active", Leg.provider != "mock", Leg.provider_ref.is_not(None)))]
        tops = [(t.id, t.provider, t.provider_ref) for t in db.scalars(
            select(TopUp).where(TopUp.status == "pending", TopUp.provider != "mock", TopUp.provider_ref.is_not(None)))]
    for lid, prov, ref in legs:
        st = provider_by_name(prov).fetch_status(ref)
        if st.state != "pending":
            confirm_leg(lid, st)
    for tid, prov, ref in tops:
        st = provider_by_name(prov).fetch_status(ref)
        if st.state != "pending":
            confirm_topup(tid, st)


def refresh_by_provider_ref(provider_name: str, ref: str) -> None:
    """Webhook path: re-confirm with the provider's status API (source of truth)."""
    with session_scope() as db:
        leg = db.scalars(select(Leg).where(Leg.provider_ref == ref)).first()
        top = None if leg else db.scalars(select(TopUp).where(TopUp.provider_ref == ref)).first()
        leg_id, top_id = (leg.id if leg else None), (top.id if top else None)
    st = provider_by_name(provider_name).fetch_status(ref)
    if leg_id and st.state != "pending":
        confirm_leg(leg_id, st)
    elif top_id and st.state != "pending":
        confirm_topup(top_id, st)


def device_resume_messages(db: Session, device_id: str) -> list[dict]:
    order = db.scalars(select(Order).where(
        Order.device_id == device_id, Order.status.in_(("awaiting_payment", "partially_paid")))
        .order_by(Order.created_at.desc())).first()
    return bill_messages(order) if order else []


def device_merchant(db: Session, device_id: str) -> Merchant | None:
    d = db.get(Device, device_id)
    return d.merchant if d else None
