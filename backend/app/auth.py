"""Phone + password accounts, opaque bearer sessions, role/ownership checks."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, session_scope
from .models import AuthSession, User, utcnow
from .money import new_id

log = logging.getLogger("zeromdr.auth")

PBKDF2_ITER = 240_000
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
VPA_RE = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z][a-zA-Z0-9.\-]{1,64}$")


# ------------------------------------------------------------------ validation

def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not PHONE_RE.match(digits):
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number")
    return digits


def validate_password(pw: str) -> None:
    if len(pw or "") < 8:
        raise HTTPException(422, "Password must be at least 8 characters")


def normalize_gstin(raw: str) -> str:
    from . import gstin
    g = (raw or "").strip().upper()
    err = gstin.problem(g)
    if err:
        raise HTTPException(422, err)
    return g


def normalize_vpa(raw: str) -> str:
    v = (raw or "").strip().lower()
    if not VPA_RE.match(v):
        raise HTTPException(422, "UPI ID must look like name@bank")
    return v


# ------------------------------------------------------------------ passwords & tokens

def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), PBKDF2_ITER).hex()
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt}${dk}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(iters)).hex()
        return hmac.compare_digest(calc, dk)
    except (ValueError, AttributeError):
        return False


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=sha256(token), user_id=user.id,
                       expires_at=utcnow() + timedelta(days=settings.session_ttl_days)))
    return token


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.get(AuthSession, sha256(token))
    if not s or s.expires_at < utcnow():
        return None
    return s.user


def revoke(db: Session, token: str) -> None:
    s = db.get(AuthSession, sha256(token))
    if s:
        db.delete(s)


# ------------------------------------------------------------------ login throttling

_fail_lock = threading.Lock()
_failures: dict[str, deque] = defaultdict(deque)
MAX_FAILS, WINDOW_S = 6, 600


def check_throttle(key: str) -> None:
    now = time.time()
    with _fail_lock:
        q = _failures[key]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= MAX_FAILS:
            raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")


def record_failure(key: str) -> None:
    with _fail_lock:
        _failures[key].append(time.time())


def clear_failures(key: str) -> None:
    with _fail_lock:
        _failures.pop(key, None)


# ------------------------------------------------------------------ FastAPI dependencies

def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, _bearer(authorization))
    if not user:
        raise HTTPException(401, "Not logged in")
    return user


def optional_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User | None:
    return user_from_token(db, _bearer(authorization))


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Not allowed for this account")
        return user
    return dep


def ensure_merchant(user: User, merchant_id: str, write: bool = False) -> None:
    if user.role == "admin" and not write:
        return
    if user.role != "merchant" or user.merchant_id != merchant_id:
        raise HTTPException(403, "Not your merchant account")


def ensure_advertiser(user: User, advertiser_id: str, write: bool = False) -> None:
    if user.role == "admin" and not write:
        return
    if user.role != "advertiser" or user.advertiser_id != advertiser_id:
        raise HTTPException(403, "Not your advertiser account")


def bootstrap_admin() -> None:
    """Create the admin account from ADMIN_PHONE / ADMIN_PASSWORD if it doesn't exist."""
    if not (settings.admin_phone and settings.admin_password):
        with session_scope() as db:
            if not db.scalars(select(User).where(User.role == "admin")).first():
                log.warning("No admin account. Set ADMIN_PHONE and ADMIN_PASSWORD in backend/.env "
                            "or run: python -m app.cli create-admin")
        return
    phone = normalize_phone(settings.admin_phone)
    with session_scope() as db:
        u = db.scalars(select(User).where(User.phone == phone)).first()
        if u:
            if u.role != "admin":
                log.error("ADMIN_PHONE %s already belongs to a %s account; admin not created", phone, u.role)
            return
        if len(settings.admin_password) < 8:
            log.error("ADMIN_PASSWORD must be at least 8 characters; admin not created")
            return
        db.add(User(id=new_id("U", 5), phone=phone, password_hash=hash_password(settings.admin_password),
                    role="admin", name="SoundShare Admin"))
        log.info("Admin account created for %s", phone)
