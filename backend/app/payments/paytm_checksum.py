"""Paytm checksum (signature) generation/verification.

Port of Paytm's official PaytmChecksum library: SHA-256 of "<payload>|<salt>",
salt appended, then AES-CBC encrypted with the merchant key and a fixed IV.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import string

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

_IV = b"@@@@&&&&####$$$$"
_SALT_CHARS = string.ascii_uppercase + string.digits + string.ascii_lowercase


def _encrypt(text: str, key: str) -> str:
    cipher = AES.new(key.encode(), AES.MODE_CBC, _IV)
    return base64.b64encode(cipher.encrypt(pad(text.encode(), 16))).decode()


def _decrypt(enc: str, key: str) -> str:
    cipher = AES.new(key.encode(), AES.MODE_CBC, _IV)
    return unpad(cipher.decrypt(base64.b64decode(enc)), 16).decode()


def _hash(params: str, salt: str) -> str:
    return hashlib.sha256(f"{params}|{salt}".encode()).hexdigest() + salt


def string_by_params(params: dict) -> str:
    vals = []
    for k in sorted(params):
        v = params[k]
        vals.append("" if v is None or str(v).lower() == "null" else str(v))
    return "|".join(vals)


def generate_signature(params: dict | str, key: str) -> str:
    if isinstance(params, dict):
        params = string_by_params(params)
    salt = "".join(secrets.choice(_SALT_CHARS) for _ in range(4))
    return _encrypt(_hash(params, salt), key)


def verify_signature(params: dict | str, key: str, checksum: str) -> bool:
    if isinstance(params, dict):
        params = {k: v for k, v in params.items() if k != "CHECKSUMHASH"}
        params = string_by_params(params)
    try:
        decrypted = _decrypt(checksum, key)
    except (ValueError, KeyError):
        return False
    salt = decrypted[-4:]
    return secrets.compare_digest(decrypted, _hash(params, salt))
