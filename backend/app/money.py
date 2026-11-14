from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal


def round_paise(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rupees_str(paise: int) -> str:
    """650000 -> '6500.00' (the format payment gateways expect)."""
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    return f"{sign}{paise // 100}.{paise % 100:02d}"


def inr(paise: int) -> str:
    """650000 -> '₹6,500.00' with Indian digit grouping."""
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    rupees, p = divmod(paise, 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}₹{s}.{p:02d}"


def new_id(prefix: str, n: int = 4) -> str:
    return f"{prefix}-{secrets.token_hex(n).upper()}"


def order_id() -> str:
    return f"O-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _words_99(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + ("" if o == 0 else f" {_ONES[o]}")


def announce_tokens(paise: int, lang: str = "en") -> tuple[list[str], str]:
    """Soundbox clip tokens + English text for an amount (Indian grouping, paise ignored).

    1,23,45,678 -> chime pre n1 crore n23 lakh n45 thousand n6 hundred n78 rupees received
    """
    r = max(0, paise // 100)
    tokens: list[str] = []
    words: list[str] = []
    if r == 0:
        tokens, words = ["n0"], ["zero"]
    else:
        crore, rem = divmod(r, 10_000_000)
        lakh, rem = divmod(rem, 100_000)
        thousand, rem = divmod(rem, 1000)
        hundred, rest = divmod(rem, 100)
        if crore:
            # Amounts >= 100 crore are unrealistic at a counter; clamp to 99 crore groups.
            c = min(crore, 99)
            tokens += [f"n{c}", "crore"]; words += [_words_99(c), "crore"]
        for val, unit in ((lakh, "lakh"), (thousand, "thousand"), (hundred, "hundred")):
            if val:
                tokens += [f"n{val}", unit]; words += [_words_99(val), unit]
        if rest:
            tokens.append(f"n{rest}"); words.append(_words_99(rest))
    # Soundbox phrasing: [chime] "Received" <amount> "rupees" "on Paytm"
    #                   hi: [chime] "Paytm पर" <amount> "रुपये" "प्राप्त हुए"
    tokens = ["chime", "pre", *tokens, "rupees", "received"]
    if lang == "hi":
        return tokens, f"Paytm पर {inr(paise)} प्राप्त हुए"
    return tokens, "Received " + " ".join(words) + " rupees on Paytm"
