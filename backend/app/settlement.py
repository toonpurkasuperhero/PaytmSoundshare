"""SoundShare settlement engine: one bill -> one QR -> payment -> counter ad money -> merchant earnings.

    create_order -> QR shown (counter ad reserved) -> confirm_leg -> begin_settlement
      -> payment_success on device -> play_ack / timeout -> finalize

Money flow for each paid bill:
  * the customer's payment goes to the merchant in full (no fee handling, no bill splitting);
  * the counter ad's money (charged only if it played fully and the bill was paid) goes:
      platform share -> this month's Soundbox rental -> the merchant's ad earnings.

All money movement happens under `money_lock` inside one DB transaction, and device messages
are sent only after the commit.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import adx, announcer, factorizer, kyc, ledger, planner, sentinel, tags
from .config import settings
from .db import money_lock, session_scope
from .hub import device_url, hub, public_url
from .models import Advertiser, Campaign, Device, Hold, LedgerEntry, Leg, Merchant, Order, OrderItem, TopUp, utcnow
from .money import announce_tokens, new_id, order_id
from .payments import PaymentStatus, ProviderError, get_provider, provider_by_name

log = logging.getLogger("zeromdr.settlement")

LATENCIES_MS: deque[float] = deque(maxlen=500)
MIN_PLAY_FRACTION = 0.8
MIC_NOISE_FLOOR_DB = -50.0
RENTAL_ACCOUNT = "soundbox_rental"
IST = timezone(timedelta(hours=5, minutes=30))


def earnings_account(merchant_id: str) -> str:
    """Ledger account holding a merchant's ad earnings (after their Soundbox rental is paid)."""
    return f"merchant_earnings:{merchant_id}"


def rental_ref(merchant_id: str, when: datetime | None = None) -> str:
    return f"rental:{merchant_id}:{(when or datetime.now(IST)).astimezone(IST):%Y-%m}"


def rental_paid(db: Session, merchant_id: str) -> int:
    return db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.ref == rental_ref(merchant_id), LedgerEntry.account == RENTAL_ACCOUNT)).scalar_one()


def rental_due(db: Session, merchant: Merchant) -> int:
    return max(0, merchant.monthly_rental_paise - rental_paid(db, merchant.id))


class SentinelBlocked(Exception):  # kept for API compatibility; bills are no longer split
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
    active = next((l for l in order.legs if l.status == "active"), None)
    if active:
        msgs.append(qr_message(order, active))
    return msgs


def qr_message(order: Order, leg: Leg) -> dict:
    return {"type": "show_qr", "orderId": order.id, "legId": leg.id, "seq": 1, "of": 1,
            "qrData": leg.qr_data or leg.qr_image_url, "amount": leg.amount_paise,
            "expiresAt": _ts(leg.expires_at)}


def _activate_leg(db: Session, order: Order, leg: Leg, merchant: Merchant) -> None:
    provider = get_provider()
    expires = utcnow() + timedelta(minutes=settings.qr_expiry_min)
    created = provider.create_payment(
        ref=leg.id, amount_paise=leg.amount_paise, description=f"{merchant.name} {order.id}",
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
                 *_ignored, **_ignored_kw) -> tuple[Order, Outbox]:
    """One bill, one payment QR for the full amount."""
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

    items = factorizer.normalize(planner.apply_catalog(db, merchant, items_in), merchant.gstin)
    total = sum(i.amount for i in items)
    oid = order_id()
    order = Order(id=oid, merchant_id=merchant.id, device_id=device_id, status="created", total_paise=total,
                  factorize=False, sentinel={"decision": "allow", "reasons": []}, division={"source": "single"})
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
    db.add(Leg(id=new_id("L", 5), order_id=oid, seq=1, of=1, label="Bill", supply_type="goods",
               supplier_gstin=merchant.gstin, amount_paise=total, item_ids=[r.id for r in rows], status="pending"))
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
    """Pick (and reserve the money for) the counter ad as the QR goes up. Nothing plays yet.

    Both formats play AFTER the payment message, so the customer always hears "payment received" first:
    normal hours = the full ad; busy hour = only a short sponsor tag, at the lower tag price.
    Charged only if the bill is paid and the Soundbox confirms the play.
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
            _apply_payment(db, order, leg, merchant, status, out)
        else:
            return
    out.flush()


def _apply_payment(db: Session, order: Order, leg: Leg, merchant: Merchant, status: PaymentStatus,
                   out: Outbox) -> None:
    leg.status = "paid"
    leg.rail = status.rail or "UNKNOWN"
    leg.payer_ref = status.payer_ref
    leg.provider_txn_id = status.txn_id
    leg.payment_mode_raw = status.raw or None
    leg.paid_at = utcnow()
    ref = f"order:{order.id}"
    ledger.post(db, ref, f"Bill paid via {leg.rail}",
                [("customer", -leg.amount_paise), (f"merchant:{merchant.id}", leg.amount_paise)])
    verdict = sentinel.check_payment(db, merchant, leg)  # e.g. a merchant paying itself to farm ad money
    if verdict["deny_subsidy"]:
        order.sentinel = {**(order.sentinel or {}), "deny_subsidy": True, "post_payment": verdict["reasons"]}
        out.events.append(("sentinel_flag", {"ref": ref, "decision": "deny_ad_money"}))
    order.status = "paid"
    order.paid_at = utcnow()
    _begin_settlement(db, order, merchant, out)


def _commit_hold(db: Session, hold: Hold, memo: str) -> None:
    hold.status = "committed"
    hold.resolved_at = utcnow()
    ledger.post(db, f"order:{hold.order_id}", memo, [
        (f"adv:{hold.advertiser_id}", -hold.amount_paise), ("sponsor_pool", hold.amount_paise)])


def _begin_settlement(db: Session, order: Order, merchant: Merchant, out: Outbox) -> None:
    deny = bool((order.sentinel or {}).get("deny_subsidy"))
    counter = db.scalars(select(Hold).where(Hold.order_id == order.id, Hold.kind.in_(("audio", "tag")),
                                            Hold.status == "reserved")).first()
    camp: Campaign | None = counter.campaign if counter else None
    tag_clip = ad_clip = None
    if counter and deny:  # no ad money from self-payments
        counter.status, counter.release_reason, counter.resolved_at = "released", "self_dealing", utcnow()
        counter, camp = None, None
    elif counter and counter.kind == "audio":
        # Normal hours: the full ad plays right after the payment message; its play_ack settles it.
        cr = camp.creative
        counter.sent_at = utcnow()
        ad_clip = {"hash": cr.audio_hash, "url": device_url(order.device_id, f"/media/audio/{cr.audio_hash}.mp3"),
                   "durationMs": cr.duration_ms or 0, "advertiser": camp.advertiser.name, "kind": "ad"}
    elif counter and counter.kind == "tag":
        try:
            h_, dur = tags.ensure(camp.advertiser.name, merchant.lang)
            counter.duration_ms, counter.sent_at = dur, utcnow()
            tag_clip = {"hash": h_, "url": device_url(order.device_id, f"/media/audio/{h_}.mp3"), "durationMs": dur,
                        "advertiser": camp.advertiser.name, "kind": "tag"}
        except Exception as e:  # no voice for the tag: don't charge for a tag that can't play
            log.warning("sponsor tag unavailable: %s", e)
            counter.status, counter.release_reason, counter.resolved_at = "released", "tag_unavailable", utcnow()
            counter, camp = None, None

    order.settlement = {"status": "pending_ack", "merchant_receives_paise": order.total_paise}
    tokens, text = announce_tokens(order.total_paise, merchant.lang)
    lang_ = merchant.lang if merchant.lang in ("en", "hi") else "en"  # local clip packs: en/hi
    msg = {
        "type": "payment_success", "orderId": order.id, "amount": order.total_paise, "lang": merchant.lang,
        "announce": tokens if lang_ == merchant.lang else announce_tokens(order.total_paise, lang_)[0],
        "announceText": text,
        "announceUrl": (device_url(order.device_id, f"/api/announce/{order.id}.mp3")
                        if announcer.available(merchant.lang) else None),
        "playId": None, "ad": None, "banner": None, "offerQr": None, "settlement": None,
    }
    if camp:
        cr = camp.creative
        msg["banner"] = cr.banner
        msg["offerQr"] = public_url(order.device_id, f"/api/offers/{cr.id}/claim?d={order.device_id or ''}")
        if ad_clip or tag_clip:  # plays right after the payment message
            msg["playId"], msg["ad"] = counter.id, ad_clip or tag_clip
    out.msgs.append(msg)
    out.events.append(("order_update", {"order_id": order.id, "status": "paid"}))

    if not counter or counter.status != "reserved":
        _finalize(db, order, out)


def _finalize(db: Session, order: Order, out: Outbox) -> None:
    """Ad money for this bill: platform share -> this month's Soundbox rental -> merchant's earnings."""
    holds = db.scalars(select(Hold).where(Hold.order_id == order.id)).all()
    if any(h.status == "reserved" for h in holds):
        return
    merchant = db.get(Merchant, order.merchant_id)
    ref = f"order:{order.id}"
    ad_money = sum(h.amount_paise for h in holds if h.status == "committed")
    platform = round(ad_money * settings.platform_surplus_take_pct / 100)
    ledger.post(db, ref, "Platform share of ad revenue", [("sponsor_pool", -platform), ("platform", platform)])
    rest = ad_money - platform
    rental = min(rest, rental_due(db, merchant))
    ledger.post(db, rental_ref(merchant.id), f"Soundbox rental paid by ads ({order.id})",
                [("sponsor_pool", -rental), (RENTAL_ACCOUNT, rental)])
    earnings = rest - rental
    ledger.post(db, ref, "Ad earnings for the merchant",
                [("sponsor_pool", -earnings), (earnings_account(merchant.id), earnings)])
    order.settlement = {
        "status": "settled",
        "merchant_receives_paise": order.total_paise,
        "ad_revenue_paise": ad_money,
        "platform_paise": platform,
        "rental_paid_paise": rental,
        "earnings_paise": earnings,
        "rental_due_after_paise": rental_due(db, merchant),
        "sponsors": [{"advertiser_id": h.advertiser_id, "name": h.advertiser.name, "kind": h.kind,
                      "amount_paise": h.amount_paise, "status": h.status,
                      **({"release_reason": h.release_reason} if h.release_reason else {})} for h in holds],
    }
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
        what = "sponsor tag" if hold.kind == "tag" else "ad after payment"
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
    now = utcnow()
    cutoff = now - timedelta(seconds=settings.play_ack_timeout_s)
    with money_lock, session_scope() as db:
        # Only plays actually sent to a device and never confirmed. The device plays the payment
        # message first, then the clip, so allow for both before calling a play stale.
        sent = db.scalars(select(Hold).where(Hold.status == "reserved", Hold.verified.is_(False),
                                             Hold.sent_at.is_not(None), Hold.sent_at < cutoff)).all()
        stale = [h for h in sent if h.sent_at < cutoff - timedelta(milliseconds=(h.duration_ms or 0) + 8000)]
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
        kyc.activate_ready(db, db.get(Advertiser, advertiser_id))
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
            kyc.activate_ready(db, db.get(Advertiser, t.advertiser_id))
        elif status.state in ("failed", "expired"):
            t.status = "failed"


# ------------------------------------------------------------------ provider polling

def poll_once() -> None:
    """Poll non-mock providers for pending bills / top-ups (works without public webhooks)."""
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
