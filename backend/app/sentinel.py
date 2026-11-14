"""Anti-Structuring Sentinel: deterministic rules that run before and after payment.

Pre-payment (block): a split plan must follow legal supply boundaries.
Post-payment (deny subsidy / flag): self-dealing, payer velocity, threshold hugging.
A GNN scorer can be plugged in later via `score_graph` (stretch goal). The rules
here are what actually gate money in the prototype.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .factorizer import MAX_LEGS, LegPlan, NormItem
from .models import Leg, Merchant, Order, SentinelFlag, utcnow

ZERO_MDR_CEILING = 200000  # ₹2,000 in paise
HUG_BAND = 10000           # legs within ₹100 below the ceiling count as "hugging"


def _flag(db: Session, ref: str, rule: str, severity: str, action: str, detail: str) -> dict:
    db.add(SentinelFlag(ref=ref, rule=rule, severity=severity, action=action, detail=detail))
    return {"rule": rule, "severity": severity, "action": action, "detail": detail}


def check_plan(db: Session, merchant: Merchant, items: list[NormItem], legs: list[LegPlan],
               custom: bool, ref: str, record: bool = True) -> dict:
    """Validate a leg plan. `custom` = the plan came from AI or a person (full checks).
    `record=False` is a dry run (plan preview): nothing is written to the flag log."""
    reasons: list[dict] = []
    block = False

    if len(legs) > MAX_LEGS:
        block = True
        reasons.append({"rule": "MAX_LEGS", "detail": f"{len(legs)} legs requested; at most {MAX_LEGS} allowed."})

    if custom:
        seen: dict[int, int] = {}
        for lp in legs:
            for i in lp.item_idx:
                seen[i] = seen.get(i, 0) + 1
        missing = [i for i in range(len(items)) if i not in seen]
        dup = [i for i, c in seen.items() if c > 1]
        if missing or dup:
            block = True
            reasons.append({"rule": "WHOLE_LINES",
                            "detail": "Every bill line must appear in exactly one leg "
                                      f"(missing {missing or '-'}, duplicated {dup or '-'})."})
        by_key: dict[tuple[str, str], int] = {}
        for lp in legs:
            for key in {items[i].boundary for i in lp.item_idx}:
                by_key[key] = by_key.get(key, 0) + 1
        for (gstin, supply), n in by_key.items():
            if n > 1:
                block = True
                reasons.append({"rule": "SAME_SUPPLY_SPLIT",
                                "detail": f"{n} legs carry {supply} from the same supplier ({gstin}). "
                                          "Splitting one supply into several payments to stay under the "
                                          "₹2,000 zero-MDR ceiling is structuring."})

    # History check: does this merchant keep producing legs just under the ceiling?
    since = utcnow() - timedelta(hours=24)
    q = (select(Leg.amount_paise).join(Order, Leg.order_id == Order.id)
         .where(Order.merchant_id == merchant.id, Order.created_at >= since))
    recent = [a for (a,) in db.execute(q).all()]
    hugging = [a for a in recent if ZERO_MDR_CEILING - HUG_BAND <= a <= ZERO_MDR_CEILING]
    planned_hug = [lp for lp in legs if ZERO_MDR_CEILING - HUG_BAND <= lp.amount <= ZERO_MDR_CEILING]
    if planned_hug and len(recent) >= 5 and len(hugging) / max(1, len(recent)) > 0.4:
        reasons.append({"rule": "THRESHOLD_HUGGING",
                        "detail": f"{len(hugging)}/{len(recent)} legs in 24h sit just under ₹2,000."})
        if record:
            _flag(db, ref, "THRESHOLD_HUGGING", "warn", "flag", reasons[-1]["detail"])

    decision = "block" if block else ("flag" if reasons else "allow")
    if record and block:
        for r in reasons:
            if r["rule"] != "THRESHOLD_HUGGING":
                _flag(db, ref, r["rule"], "high", "block", r["detail"])
    return {"decision": decision, "reasons": reasons}


def check_payment(db: Session, merchant: Merchant, leg: Leg) -> dict:
    """Runs on every confirmed leg. Returns {'deny_subsidy': bool, 'reasons': [...]}."""
    reasons = []
    deny = False
    payer = (leg.payer_ref or "").strip().lower()
    ref = f"order:{leg.order_id}"

    if payer and merchant.vpa and payer == merchant.vpa.lower():
        deny = True
        reasons.append(_flag(db, ref, "SELF_DEALING", "high", "deny_subsidy",
                             f"Payer {payer} is the merchant's own VPA. No sponsor subsidy for self-payments."))

    if payer:
        since = utcnow() - timedelta(minutes=10)
        n = db.execute(
            select(func.count(Leg.id)).join(Order, Leg.order_id == Order.id)
            .where(Order.merchant_id == merchant.id, Leg.payer_ref == leg.payer_ref,
                   Leg.status == "paid", Leg.paid_at >= since)
        ).scalar_one()
        if n >= 5:
            deny = True
            reasons.append(_flag(db, ref, "PAYER_VELOCITY", "warn", "deny_subsidy",
                                 f"Payer {payer} made {n} payments here in 10 minutes."))
    return {"deny_subsidy": deny, "reasons": reasons}
