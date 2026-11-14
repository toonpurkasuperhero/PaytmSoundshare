"""GSTIN validation: structure, state code and the official check digit.

A GSTIN is 15 characters: 2-digit state code + 10-character PAN + entity number + 'Z' + check digit.
The check digit (base-36, alternating weights 1/2) catches typos and most made-up numbers
before any human or API looks at it. It does NOT prove the business exists or is active;
that is the KYC step (see app.kyc).
"""
from __future__ import annotations

import re

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PATTERN = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
# State/UT codes in use (01-38), plus 97 (Other Territory) and 99 (Centre Jurisdiction).
VALID_STATES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


def check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARS[(36 - total % 36) % 36]


def problem(gstin: str) -> str | None:
    """None if the GSTIN is well-formed with a correct check digit, else a human-readable reason."""
    g = (gstin or "").strip().upper()
    m = PATTERN.match(g)
    if not m:
        return "GSTIN must be 15 characters like 29ABCDE1234F1Z5 (state code, PAN, entity number, Z, check digit)"
    if m.group(1) not in VALID_STATES:
        return f"GSTIN state code {m.group(1)} is not a valid Indian state/UT code"
    if check_digit(g[:14]) != g[14]:
        return "GSTIN check digit doesn't match. Please re-check the number on your GST certificate"
    return None


def pan(gstin: str) -> str:
    return gstin[2:12]


def make(state: str, pan_: str, entity: str = "1") -> str:
    """Build a GSTIN with the correct check digit (used for demo data and tests)."""
    first14 = f"{state}{pan_}{entity}Z"
    return first14 + check_digit(first14)
