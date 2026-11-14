"""MDR engine: rate card lookup + GST, all in integer paise."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import yaml

from .config import CONFIG_DIR
from .money import round_paise

RAILS = ["UPI_BANK", "UPI_RUPAY_CC", "UPI_PPI", "DEBIT_CARD", "CREDIT_CARD", "NET_BANKING", "UNKNOWN"]


@lru_cache(maxsize=1)
def rate_card() -> dict:
    with open(CONFIG_DIR / "mdr_rates.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class MdrQuote:
    rail: str
    amount_paise: int
    rate: Decimal
    mdr_paise: int
    gst_paise: int

    @property
    def total_paise(self) -> int:
        return self.mdr_paise + self.gst_paise


def quote(amount_paise: int, rail: str | None) -> MdrQuote:
    card = rate_card()
    rails = card["rails"]
    rail = rail if rail in rails else "UNKNOWN"
    rate = Decimal("0")
    for slab in rails[rail]["slabs"]:
        upto = slab.get("upto_paise")
        if upto is None or amount_paise <= upto:
            rate = Decimal(str(slab["rate"]))
            break
    mdr = round_paise(Decimal(amount_paise) * rate)
    gst = round_paise(Decimal(mdr) * Decimal(str(card["gst_rate"])))
    return MdrQuote(rail, amount_paise, rate, mdr, gst)


def mdr_total(amount_paise: int, rail: str | None) -> int:
    return quote(amount_paise, rail).total_paise


def public_rates() -> dict:
    card = rate_card()
    return {
        "gst_rate": float(card["gst_rate"]),
        "rails": {
            k: {"label": v["label"], "slabs": [{"upto_paise": s.get("upto_paise"), "rate": float(s["rate"])} for s in v["slabs"]]}
            for k, v in card["rails"].items()
        },
    }
