"""Bill plan = AI classification + AI division, validated by the Sentinel and priced."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import factorizer, llm, sentinel
from .factorizer import ESTIMATE_RAILS, LegPlan, NormItem
from .mdr import mdr_total, rate_card
from .models import CatalogItem, Merchant
from .money import inr


def _leg_dict(lp: LegPlan) -> dict:
    return {"item_indexes": lp.item_idx, "label": lp.label, "supply_type": lp.supply_type,
            "amount_paise": lp.amount, "reason": lp.reason}


def _item_dict(it: NormItem, raw: dict) -> dict:
    return {"name": it.name, "qty": it.qty, "unit_price": it.unit_price, "amount_paise": it.amount,
            "hsn_sac": it.hsn_sac, "supply_type": it.supply_type, "category": it.category, "brand": it.brand,
            "supplier_gstin": it.supplier_gstin, "catalog_item_id": raw.get("catalog_item_id"),
            "classification_source": it.source}


def apply_catalog(db: Session, merchant: Merchant, items_in: list[dict]) -> list[dict]:
    """Catalog lines take their codes from the merchant's catalog in the DB, not from the client."""
    out = []
    for it in items_in:
        it = dict(it)
        cid = it.get("catalog_item_id")
        if cid:
            c = db.get(CatalogItem, cid)
            if not c or c.merchant_id != merchant.id:
                raise LookupError(f"catalog item {cid} not found")
            it.update(hsn_sac=c.hsn_sac, category=c.category, brand=c.brand, classification_source="catalog")
        out.append(it)
    return out


def build(db: Session, merchant: Merchant, items_in: list[dict], factorize: bool) -> tuple[dict, list[NormItem], list[LegPlan]]:
    items_in = apply_catalog(db, merchant, items_in)
    classified, csrc, creason = factorizer.classify(items_in)
    items = factorizer.normalize(classified, merchant.gstin)
    rule = factorizer.partition(items, True)
    model = None
    if not factorize:
        legs = factorizer.partition(items, False)
        source, reason, rationale = "single", None, "Factorization is turned off, so the bill is paid in one go."
    elif len(rule) == 1:
        legs = rule
        source, reason = "single", None
        rationale = ("Every line is the same kind of supply from one supplier, so there is only one legal "
                     "invoice. Splitting it would be structuring.")
    else:
        try:
            ai_legs, rationale = factorizer.ai_divide(items)
            verdict = sentinel.check_plan(db, merchant, items, ai_legs, custom=True, ref="plan", record=False)
            if verdict["decision"] == "block":
                raise llm.AIError("AI split rejected by Sentinel: " +
                                  "; ".join(r["detail"] for r in verdict["reasons"]))
            extra, rail = factorizer.extra_cost_vs(ai_legs, rule)
            if extra > 0:
                raise llm.AIError(f"AI split would cost {inr(extra)} more in fees ({rail}) than the "
                                  "supply-boundary split")
            legs, source, reason, model = ai_legs, "ai", None, llm.last_model()
        except llm.AIError as e:
            legs, source, reason = rule, "fallback", str(e)
            rationale = "Split along supply boundaries by the rule engine: one invoice per supplier and goods/services."
    verdict = sentinel.check_plan(db, merchant, items, legs, custom=True, ref="plan", record=False)
    total = sum(i.amount for i in items)
    labels = rate_card()["rails"]
    by_rail = []
    for rail in ESTIMATE_RAILS:
        single, split = mdr_total(total, rail), factorizer.estimate_mdr(legs, rail)
        by_rail.append({"rail": rail, "label": labels[rail]["label"], "mdr_single_paise": single,
                        "mdr_split_paise": split, "saving_paise": max(0, single - split)})
    worst = max(by_rail, key=lambda r: r["mdr_single_paise"])
    plan = {
        "items": [_item_dict(it, items_in[it.idx]) for it in items],
        "legs": [_leg_dict(l) for l in legs],
        "source": source, "fallback_reason": reason, "model": model, "rationale": rationale,
        "classification": {"source": csrc, "fallback_reason": creason},
        "estimate": {
            "note": "The customer chooses how to pay; the fee is charged at the rate of the method actually used.",
            "by_rail": by_rail,
            # headline numbers = the most expensive way the customer could pay
            "worst_case_rail": worst["rail"], "mdr_single_paise": worst["mdr_single_paise"],
            "mdr_split_paise": worst["mdr_split_paise"], "saving_paise": worst["saving_paise"],
        },
        "sentinel": verdict,
    }
    return plan, items, legs
