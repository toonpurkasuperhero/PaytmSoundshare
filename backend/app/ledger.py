"""Double-entry ledger. Each transaction is a set of signed postings that sum to zero.

A positive amount means money flowed INTO the account.

Accounts:
  customer           - payers at the counter (source of bill money)
  merchant:<id>      - merchant settlement account
  acquirer           - acquiring bank / network MDR (paid in full, always)
  sponsor_pool       - SoundShare clearing pool funded by ads (per order, always emptied)
  shared_pool        - SoundShare pool: ad surplus shared across merchants (fees, then rentals)
  soundbox_rental    - Soundbox rental paid to Paytm by ads (ref rental:<merchant>:<YYYY-MM>)
  adv:<id>           - advertiser prepaid wallet
  platform           - Paytm platform spread
  funding            - advertiser top-ups (external money in)
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .hub import hub
from .models import Advertiser, LedgerEntry, Merchant
from .money import new_id

STATIC_LABELS = {
    "customer": "Customers",
    "acquirer": "Acquirer / Network MDR",
    "sponsor_pool": "Ad clearing (per sale)",
    "shared_pool": "SoundShare pool",
    "soundbox_rental": "Soundbox rental (Paytm)",
    "platform": "Paytm Platform Spread",
    "funding": "Advertiser Top-ups",
}


class UnbalancedTxn(ValueError):
    pass


def post(db: Session, ref: str, memo: str, postings: list[tuple[str, int]]) -> str | None:
    postings = [(a, int(v)) for a, v in postings if int(v) != 0]
    if not postings:
        return None
    if sum(v for _, v in postings) != 0:
        raise UnbalancedTxn(f"{memo}: postings sum to {sum(v for _, v in postings)}")
    txn = new_id("TX", 5)
    for account, amount in postings:
        db.add(LedgerEntry(txn_id=txn, ref=ref, memo=memo, account=account, amount_paise=amount))
    db.flush()
    hub.emit("ledger_post", txn_id=txn, ref=ref, memo=memo)
    return txn


def balance(db: Session, account: str) -> int:
    return db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(LedgerEntry.account == account)
    ).scalar_one()


def _labels(db: Session) -> dict[str, str]:
    labels = dict(STATIC_LABELS)
    for m in db.scalars(select(Merchant)):
        labels[f"merchant:{m.id}"] = m.name
    for a in db.scalars(select(Advertiser)):
        labels[f"adv:{a.id}"] = a.name
    return labels


def balances(db: Session) -> list[dict]:
    labels = _labels(db)
    rows = db.execute(
        select(LedgerEntry.account, func.sum(LedgerEntry.amount_paise)).group_by(LedgerEntry.account)
    ).all()
    out = [{"account": a, "label": labels.get(a, a), "balance_paise": int(b)} for a, b in rows]
    order = {"customer": 0, "funding": 1}
    out.sort(key=lambda r: (order.get(r["account"], 5), r["account"]))
    return out


def entries(db: Session, ref: str | None = None, limit: int = 100) -> list[dict]:
    q = select(LedgerEntry).order_by(LedgerEntry.id.desc()).limit(limit)
    if ref:
        q = q.where(LedgerEntry.ref == ref)
    labels = _labels(db)
    return [{
        "txn_id": e.txn_id, "ref": e.ref, "memo": e.memo, "account": e.account,
        "label": labels.get(e.account, e.account), "amount_paise": e.amount_paise, "ts": e.ts,
    } for e in db.scalars(q)]


def flows(db: Session, order_id: str | None = None) -> dict:
    """Aggregate postings into source->target money flows for a Sankey diagram."""
    q = select(LedgerEntry).order_by(LedgerEntry.id)
    if order_id:
        q = q.where(LedgerEntry.ref == f"order:{order_id}")
    by_txn: dict[str, list[LedgerEntry]] = {}
    for e in db.scalars(q):
        by_txn.setdefault(e.txn_id, []).append(e)

    agg: dict[tuple[str, str], int] = {}
    for postings in by_txn.values():
        srcs = [[e.account, -e.amount_paise] for e in postings if e.amount_paise < 0]
        dsts = [[e.account, e.amount_paise] for e in postings if e.amount_paise > 0]
        i = j = 0
        while i < len(srcs) and j < len(dsts):
            amt = min(srcs[i][1], dsts[j][1])
            key = (srcs[i][0], dsts[j][0])
            agg[key] = agg.get(key, 0) + amt
            srcs[i][1] -= amt
            dsts[j][1] -= amt
            if srcs[i][1] == 0:
                i += 1
            if dsts[j][1] == 0:
                j += 1

    labels = _labels(db)
    used = sorted({a for k in agg for a in k})
    return {
        "nodes": [{"id": a, "label": labels.get(a, a)} for a in used],
        "links": [{"source": s, "target": t, "amount_paise": v} for (s, t), v in agg.items() if v > 0],
    }
