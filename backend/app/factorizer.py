"""Semantic cart factorizer (AI-first).

1. Parse: bill text or photo -> line items (Gemini; a regex parser for text only when the AI fails).
2. Classify: every uncoded line gets HSN/SAC, supply type, category and brand (Gemini; a keyword table when the AI fails).
3. Divide: Gemini proposes the leg split with reasons. The proposal is accepted only if
   the Sentinel finds it legal (supply boundaries, whole lines, <= 3 legs) and it doesn't cost
   more MDR than the deterministic boundary split, which is also the fallback.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import hsn, llm, mdr

log = logging.getLogger("zeromdr.factorizer")
MAX_LEGS = 3
# Before payment we don't know how the customer will pay, so estimates are shown for every method.
ESTIMATE_RAILS = ["UPI_BANK", "UPI_RUPAY_CC", "UPI_PPI", "DEBIT_CARD", "CREDIT_CARD", "NET_BANKING"]
HSN_RE = re.compile(r"^\d{4,8}$")


class ParseFailed(RuntimeError):
    pass


@dataclass
class NormItem:
    idx: int
    name: str
    qty: int
    unit_price: int
    hsn_sac: str
    supply_type: str
    category: str
    brand: str | None
    supplier_gstin: str
    source: str = "manual"

    @property
    def amount(self) -> int:
        return self.qty * self.unit_price

    @property
    def boundary(self) -> tuple[str, str]:
        return (self.supplier_gstin, self.supply_type)


@dataclass
class LegPlan:
    item_idx: list[int]
    supply_type: str
    supplier_gstin: str
    amount: int
    label: str = ""
    reason: str = ""
    codes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ classification

CLASSIFY_SCHEMA = {
    "type": "ARRAY",
    "items": {"type": "OBJECT", "properties": {
        "index": {"type": "INTEGER"},
        "hsn_sac": {"type": "STRING", "description": "4-8 digit HSN for goods, or SAC starting with 99 for services"},
        "supply_type": {"type": "STRING", "enum": ["goods", "services"]},
        "category": {"type": "STRING", "description": "one lowercase word, e.g. appliance, services, bakery"},
        "brand": {"type": "STRING", "description": "lowercase brand name, or empty string"},
    }, "required": ["index", "hsn_sac", "supply_type", "category", "brand"]},
}


def _needs_codes(it: dict) -> bool:
    return not (it.get("hsn_sac") and HSN_RE.match(str(it["hsn_sac"]).strip()) and it.get("category"))


def classify(items: list[dict]) -> tuple[list[dict], str, str | None]:
    """Fill hsn_sac / category / brand on items that lack them.
    Returns (items, source, fallback_reason). Items already coded keep their codes."""
    todo = [i for i, it in enumerate(items) if _needs_codes(it)]
    out = [dict(it) for it in items]
    for it in out:
        if not it.get("classification_source"):
            it["classification_source"] = "catalog" if it.get("catalog_item_id") else "manual"
    if not todo:
        return out, "none", None
    try:
        listing = "\n".join(f'{i}. "{items[i]["name"]}" @ Rs {int(items[i].get("unit_price") or 0) / 100:.2f}'
                            for i in todo)
        res = llm.generate_json(
            "Classify these Indian retail bill lines for GST invoicing. For each, give the most specific "
            "HSN code (goods) or SAC code (services, always starting with 99), whether it is goods or services, "
            "a one-word category and the brand if the name contains one.\n" + listing,
            schema=CLASSIFY_SCHEMA, temperature=0.0, task="classify")
        by_idx = {int(r["index"]): r for r in res if isinstance(r, dict) and "index" in r}
        missing = [i for i in todo if i not in by_idx]
        if missing:
            raise llm.AIError(f"AI skipped lines {missing}")
        for i in todo:
            r = by_idx[i]
            code = re.sub(r"\D", "", str(r.get("hsn_sac", "")))
            if not HSN_RE.match(code):
                raise llm.AIError(f"AI gave invalid HSN/SAC '{r.get('hsn_sac')}' for line {i}")
            out[i].update(hsn_sac=code, category=str(r.get("category") or "general").lower()[:40],
                          brand=(str(r.get("brand") or "").lower()[:40] or out[i].get("brand") or None),
                          classification_source="ai")
        return out, "ai", None
    except llm.AIError as e:
        for i in todo:
            code, cat = hsn.classify(out[i]["name"])
            out[i].update(hsn_sac=out[i].get("hsn_sac") or code, category=out[i].get("category") or cat,
                          brand=out[i].get("brand") or hsn.detect_brand(out[i]["name"]),
                          classification_source="fallback")
        return out, "fallback", str(e)


def normalize(items: list[dict], merchant_gstin: str) -> list[NormItem]:
    out: list[NormItem] = []
    for i, it in enumerate(items):
        name = str(it.get("name", "")).strip() or f"Item {i + 1}"
        code = str(it.get("hsn_sac") or hsn.classify(name)[0]).strip()
        out.append(NormItem(
            idx=i, name=name, qty=max(1, int(it.get("qty") or 1)), unit_price=max(0, int(it.get("unit_price") or 0)),
            hsn_sac=code, supply_type="services" if hsn.is_service_code(code) else "goods",
            category=(it.get("category") or hsn.classify(name)[1]),
            brand=(it.get("brand") or hsn.detect_brand(name)),
            supplier_gstin=(it.get("supplier_gstin") or merchant_gstin).upper(),
            source=it.get("classification_source") or "manual",
        ))
    return out


# ------------------------------------------------------------------ partitioning

def _label(supply_type: str, codes: list[str], n_items: int) -> str:
    kind = "Services" if supply_type == "services" else "Goods"
    tag = "SAC" if supply_type == "services" else "HSN"
    uniq = sorted(set(codes))
    return f"{kind} ({tag} {uniq[0]})" if len(uniq) == 1 else f"{kind} ({n_items} items)"


def finish(legs: list[LegPlan], items: list[NormItem]) -> list[LegPlan]:
    for lp in legs:
        lp.codes = [items[i].hsn_sac for i in lp.item_idx]
        lp.amount = sum(items[i].amount for i in lp.item_idx)
        types = {items[i].supply_type for i in lp.item_idx}
        lp.supply_type = types.pop() if len(types) == 1 else "mixed"
        lp.label = _label(lp.supply_type, lp.codes, len(lp.item_idx)) if lp.supply_type != "mixed" \
            else f"Mixed ({len(lp.item_idx)} items)"
    legs.sort(key=lambda l: l.amount)
    if len(legs) == 1:
        legs[0].label = "Full bill"
    return legs


def partition(items: list[NormItem], factorize: bool) -> list[LegPlan]:
    """Deterministic boundary split: one leg per (supplier GSTIN, goods/services)."""
    if not items:
        return []
    if not factorize:
        return finish([LegPlan([i.idx for i in items], items[0].supply_type, items[0].supplier_gstin, 0,
                               reason="Factorization is off for this bill.")], items)
    groups: dict[tuple[str, str], LegPlan] = {}
    for it in items:
        g = groups.setdefault(it.boundary, LegPlan([], it.supply_type, it.supplier_gstin, 0))
        g.item_idx.append(it.idx)
    legs = list(groups.values())
    while len(legs) > MAX_LEGS:  # at most 3 scans: merge the two smallest groups
        legs.sort(key=lambda l: sum(items[i].amount for i in l.item_idx))
        legs[1].item_idx = sorted(legs[0].item_idx + legs[1].item_idx)
        legs = legs[1:]
    for lp in legs:
        kind = "services (SAC)" if lp.supply_type == "services" else "goods (HSN)"
        lp.reason = f"All {kind} lines supplied under GSTIN {lp.supplier_gstin}: one tax invoice."
    return finish(legs, items)


def legs_from_indexes(items: list[NormItem], groups: list[list[int]], reasons: list[str] | None = None) -> list[LegPlan]:
    legs = []
    for n, g in enumerate(groups):
        idxs = [i for i in g if 0 <= i < len(items)]
        if not idxs:
            continue
        first = items[idxs[0]]
        legs.append(LegPlan(idxs, first.supply_type, first.supplier_gstin, 0,
                            reason=(reasons[n] if reasons and n < len(reasons) else "")))
    return finish(legs, items)


def estimate_mdr(legs: list[LegPlan], rail: str) -> int:
    return sum(mdr.mdr_total(l.amount, rail) for l in legs)


def extra_cost_vs(legs: list[LegPlan], baseline: list[LegPlan]) -> tuple[int, str | None]:
    """Largest extra fee `legs` would cost over `baseline` across payment methods (0 if never worse)."""
    worst, worst_rail = 0, None
    for rail in ESTIMATE_RAILS:
        d = estimate_mdr(legs, rail) - estimate_mdr(baseline, rail)
        if d > worst:
            worst, worst_rail = d, rail
    return worst, worst_rail


DIVIDE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "legs": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "item_indexes": {"type": "ARRAY", "items": {"type": "INTEGER"}},
            "reason": {"type": "STRING", "description": "one sentence: why this is a separate taxable supply"},
        }, "required": ["item_indexes", "reason"]}},
        "rationale": {"type": "STRING", "description": "two sentences max, for the cashier"},
    },
    "required": ["legs", "rationale"],
}


def ai_divide(items: list[NormItem]) -> tuple[list[LegPlan], str]:
    """Ask Gemini for the split. Raises llm.AIError. The caller must validate the result."""
    lines = "\n".join(
        f"{i.idx}. {i.name} | qty {i.qty} | Rs {i.amount / 100:.2f} | {i.supply_type} | HSN/SAC {i.hsn_sac} | "
        f"supplier GSTIN {i.supplier_gstin}" for i in items)
    res = llm.generate_json(
        "You split an Indian retail bill into separate payment legs, each a separate GST tax invoice, to lower "
        "the merchant's payment fee (MDR). Payments of Rs 2,000 or less carry zero MDR on many rails.\n"
        "LEGAL RULES (mandatory):\n"
        "- A leg may only separate genuinely different supplies: different supplier GSTIN, or goods (HSN) vs "
        "services (SAC 99xx).\n"
        "- Never split one line across legs; every line goes in exactly one leg.\n"
        "- Never create two legs with the same supplier GSTIN and the same supply type (that is structuring).\n"
        f"- At most {MAX_LEGS} legs. If no legal split exists, return a single leg with all lines.\n"
        "Use the 0-based line numbers as item_indexes.\n\nBILL LINES:\n" + lines,
        schema=DIVIDE_SCHEMA, temperature=0.0, task="divide")
    if not isinstance(res, dict) or not res.get("legs"):
        raise llm.AIError("AI returned no legs")
    groups = [[int(x) for x in l.get("item_indexes", [])] for l in res["legs"]]
    reasons = [str(l.get("reason", ""))[:300] for l in res["legs"]]
    return legs_from_indexes(items, groups, reasons), str(res.get("rationale", ""))[:600]


# ------------------------------------------------------------------ parsing

PARSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "name": {"type": "STRING"},
        "qty": {"type": "INTEGER"},
        "unit_price_rupees": {"type": "NUMBER"},
        "hsn_sac": {"type": "STRING"},
        "category": {"type": "STRING"},
        "brand": {"type": "STRING"},
    }, "required": ["name", "qty", "unit_price_rupees", "hsn_sac", "category", "brand"]}}},
    "required": ["items"],
}
PARSE_PROMPT = (
    "Extract every purchased line item from this Indian retail bill. Ignore totals, subtotals, taxes, "
    "discount summaries and payment lines. unit_price_rupees is the price of ONE unit (divide the line total "
    "by qty if only the total is shown). hsn_sac: printed code if present, else your best 4-8 digit HSN "
    "(goods) or SAC starting with 99 (services). category: one lowercase word. brand: lowercase or empty."
)


def _clean_ai_items(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise llm.AIError("AI did not return an items list")
    out = []
    for d in data["items"]:
        try:
            price = round(float(d["unit_price_rupees"]) * 100)
            name = str(d["name"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not name or price <= 0:
            continue
        code = re.sub(r"\D", "", str(d.get("hsn_sac", "")))
        out.append({"name": name[:160], "qty": max(1, int(d.get("qty") or 1)), "unit_price": price,
                    "hsn_sac": code if HSN_RE.match(code) else None,
                    "category": (str(d.get("category") or "").lower()[:40] or None),
                    "brand": (str(d.get("brand") or "").lower()[:40] or None),
                    "classification_source": "ai"})
    if not out:
        raise llm.AIError("AI found no line items")
    return out


def parse_text(text: str) -> dict:
    try:
        items = _clean_ai_items(llm.generate_json(PARSE_PROMPT + "\n\nBILL:\n" + text, schema=PARSE_SCHEMA,
                                                  temperature=0.0, task="parse_text"))
        return {"items": items, "source": "ai", "fallback_reason": None, "model": llm.last_model()}
    except llm.AIError as e:
        items = _parse_heuristic(text)
        for it in items:
            code, cat = hsn.classify(it["name"])
            it.update(hsn_sac=code, category=cat, brand=hsn.detect_brand(it["name"]), classification_source="fallback")
        return {"items": items, "source": "fallback", "fallback_reason": str(e), "model": None}


def parse_image(data: bytes, mime: str) -> dict:
    """Bill photo -> items. There is no non-AI fallback for images (no local OCR)."""
    try:
        items = _clean_ai_items(llm.generate_json(PARSE_PROMPT, schema=PARSE_SCHEMA,
                                                  parts=[llm.inline_part(data, mime)], temperature=0.0,
                                                  task="parse_image"))
    except llm.AIError as e:
        raise ParseFailed(f"Could not read the bill photo with AI: {e}") from e
    return {"items": items, "source": "ai", "fallback_reason": None, "model": llm.last_model()}


_LINE = re.compile(
    r"^\s*(?:(?P<qty1>\d+)\s*[xX*]\s*)?(?P<name>.*?[A-Za-z].*?)\s*"
    r"(?:(?P<qty2>\d+)\s*[xX*@]\s*)?(?:Rs\.?|INR|₹)?\s*(?P<price>\d[\d,]*(?:\.\d{1,2})?)\s*/?-?\s*$"
)


def _parse_heuristic(text: str) -> list[dict]:
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.search(r"\b(total|subtotal|gst|tax|grand)\b", line, re.I):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        qty = int(m.group("qty1") or m.group("qty2") or 1)
        price = float(m.group("price").replace(",", ""))
        items.append({"name": m.group("name").strip(" -:@"), "qty": qty, "unit_price": round(price * 100)})
    return items
