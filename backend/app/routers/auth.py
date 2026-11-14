"""Sign-up, login, logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, languages
from ..db import get_db
from ..models import Advertiser, Merchant, User
from ..money import new_id
from ..serializers import user_dict

router = APIRouter(prefix="/api/auth")


class MerchantReg(BaseModel):
    phone: str
    password: str = Field(..., max_length=128)
    name: str = Field(..., min_length=2, max_length=120)
    category: str = Field(..., min_length=2, max_length=40)
    gstin: str
    vpa: str
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    address: str | None = Field(None, max_length=300)
    lang: str = Field("en", pattern=languages.PATTERN)


class AdvertiserReg(BaseModel):
    phone: str
    password: str = Field(..., max_length=128)
    name: str = Field(..., min_length=2, max_length=120)
    type: str = Field("local", pattern="^(local|brand)$")
    category: str = Field(..., min_length=2, max_length=40)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    address: str | None = Field(None, max_length=300)


class LoginIn(BaseModel):
    phone: str
    password: str = Field(..., max_length=128)


def _new_user(db: Session, phone: str, password: str, role: str, name: str, **links) -> User:
    if db.scalars(select(User).where(User.phone == phone)).first():
        raise HTTPException(409, "An account with this mobile number already exists. Log in instead.")
    u = User(id=new_id("U", 5), phone=phone, password_hash=auth.hash_password(password), role=role,
             name=name, **links)
    db.add(u)
    return u


@router.post("/register/merchant", status_code=201)
def register_merchant(body: MerchantReg, db: Session = Depends(get_db)):
    phone = auth.normalize_phone(body.phone)
    auth.validate_password(body.password)
    m = Merchant(id=new_id("M", 4), name=body.name.strip(), category=body.category.strip().lower(),
                 gstin=auth.normalize_gstin(body.gstin), vpa=auth.normalize_vpa(body.vpa),
                 lat=body.lat, lng=body.lng, address=(body.address or "").strip() or None, lang=body.lang,
                 blocked_categories=[])
    db.add(m)
    db.flush()
    u = _new_user(db, phone, body.password, "merchant", m.name, merchant_id=m.id)
    token = auth.create_session(db, u)
    db.commit()
    return {"token": token, "user": user_dict(u)}


@router.post("/register/advertiser", status_code=201)
def register_advertiser(body: AdvertiserReg, db: Session = Depends(get_db)):
    phone = auth.normalize_phone(body.phone)
    auth.validate_password(body.password)
    if body.type == "local" and (body.lat is None or body.lng is None):
        raise HTTPException(422, "Local businesses need a location so ads reach nearby Soundboxes")
    a = Advertiser(id=new_id("A", 4), name=body.name.strip(), type=body.type,
                   category=body.category.strip().lower(), lat=body.lat, lng=body.lng,
                   address=(body.address or "").strip() or None)
    db.add(a)
    db.flush()
    u = _new_user(db, phone, body.password, "advertiser", a.name, advertiser_id=a.id)
    token = auth.create_session(db, u)
    db.commit()
    return {"token": token, "user": user_dict(u)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    phone = auth.normalize_phone(body.phone)
    key = f"{phone}|{request.client.host if request.client else ''}"
    auth.check_throttle(key)
    u = db.scalars(select(User).where(User.phone == phone)).first()
    if not u or not auth.verify_password(body.password, u.password_hash):
        auth.record_failure(key)
        raise HTTPException(401, "Wrong mobile number or password")
    auth.clear_failures(key)
    token = auth.create_session(db, u)
    db.commit()
    return {"token": token, "user": user_dict(u)}


@router.get("/me")
def me(user: User = Depends(auth.current_user)):
    return user_dict(user)


@router.post("/logout")
def logout(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    token = auth._bearer(authorization)
    if token:
        auth.revoke(db, token)
        db.commit()
    return {"ok": True}
