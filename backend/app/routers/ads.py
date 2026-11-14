"""Advertisers, wallet top-ups, campaigns, AI transcription, geofence lookup, offer claims."""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import adx, auth, creative, kyc, languages, llm, settlement
from ..db import get_db, money_lock
from ..hub import hub
from ..models import Advertiser, Campaign, Claim, Creative, Device, TopUp, User
from ..money import new_id
from ..payments import ProviderError, provider_by_name
from ..serializers import advertiser_dict, campaign_dict, topup_dict

router = APIRouter(prefix="/api")
MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4",
               "audio/aac", "audio/flac"}


def _adv(db: Session, aid: str) -> Advertiser:
    a = db.get(Advertiser, aid)
    if not a:
        raise HTTPException(404, "advertiser not found")
    return a


def _own_adv(user: User) -> str:
    if user.role != "advertiser" or not user.advertiser_id:
        raise HTTPException(403, "Advertiser account required")
    return user.advertiser_id


@router.get("/advertisers")
def list_advertisers(db: Session = Depends(get_db), _: User = Depends(auth.require("admin"))):
    return [advertiser_dict(db, a, with_stats=True) for a in db.scalars(select(Advertiser).order_by(Advertiser.created_at))]


@router.get("/advertisers/{aid}")
def get_advertiser(aid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.ensure_advertiser(user, aid)
    return advertiser_dict(db, _adv(db, aid), with_stats=True)


class AdvertiserPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    gstin: str | None = Field(None, min_length=15, max_length=15)
    category: str | None = Field(None, min_length=2, max_length=40)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    address: str | None = Field(None, max_length=300)


@router.patch("/advertisers/{aid}")
def patch_advertiser(aid: str, body: AdvertiserPatch, db: Session = Depends(get_db),
                     user: User = Depends(auth.current_user)):
    auth.ensure_advertiser(user, aid, write=True)
    a = _adv(db, aid)
    data = body.model_dump(exclude_unset=True)
    new_gstin = data.pop("gstin", None)
    if new_gstin:
        g = auth.normalize_gstin(new_gstin)
        other = db.scalars(select(Advertiser).where(Advertiser.gstin == g, Advertiser.id != a.id)).first()
        if other:
            raise HTTPException(409, "An advertiser with this GSTIN is already registered")
        kyc.submit(db, a, g)
    for k, v in data.items():
        setattr(a, k, v.lower() if k == "category" and v else v)
    if body.name:
        user.name = a.name
    db.commit()
    return advertiser_dict(db, a, with_stats=True)


class TopUpIn(BaseModel):
    amount_paise: int = Field(..., ge=100, le=10_000_000)


@router.post("/advertisers/{aid}/topup", status_code=201)
def topup(aid: str, body: TopUpIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.ensure_advertiser(user, aid, write=True)
    _adv(db, aid)
    try:
        with money_lock:
            t = settlement.create_topup(db, aid, body.amount_paise)
    except ProviderError as e:
        raise HTTPException(502, f"Payment provider error: {e}")
    hub.emit("topup", advertiser_id=aid, status=t.status)
    return topup_dict(t)


@router.get("/advertisers/{aid}/topups")
def list_topups(aid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.ensure_advertiser(user, aid)
    q = select(TopUp).where(TopUp.advertiser_id == aid).order_by(TopUp.created_at.desc()).limit(50)
    return [topup_dict(t) for t in db.scalars(q)]


@router.get("/topups/{tid}")
def get_topup(tid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    t = db.get(TopUp, tid)
    if not t:
        raise HTTPException(404, "top-up not found")
    auth.ensure_advertiser(user, t.advertiser_id)
    if t.status == "pending" and t.provider != "mock" and t.provider_ref:
        st = provider_by_name(t.provider).fetch_status(t.provider_ref)
        if st.state != "pending":
            settlement.confirm_topup(t.id, st)
            db.commit()
            db.expire_all()  # confirmed in another session: re-read
            t = db.get(TopUp, tid)
    return topup_dict(t)


# ------------------------------------------------------------------ AI transcription

@router.post("/ai/transcribe")
async def transcribe(audio: UploadFile = File(...), lang: str = Form("en"),
                     user: User = Depends(auth.require("advertiser", "merchant"))):
    mime = (audio.content_type or "").split(";")[0].lower()
    if mime not in AUDIO_TYPES:
        raise HTTPException(415, f"Unsupported audio type {mime or 'unknown'}")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Voice note must be 2 MB or smaller")
    try:
        text = await run_in_threadpool(llm.transcribe, data, mime, lang if lang in languages.LANGS else "en")
    except llm.AIError as e:
        raise HTTPException(502, f"AI transcription failed: {e}")
    return {"text": text, "source": "ai", "model": llm.last_model()}


# ------------------------------------------------------------------ geofence

@router.get("/geo/soundboxes")
def soundboxes_in_radius(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
                         radius_m: int = Query(500, ge=0, le=50_000), db: Session = Depends(get_db),
                         _: User = Depends(auth.require("advertiser", "admin"))):
    out = []
    for d in db.scalars(select(Device)):
        m = d.merchant
        dist = adx.haversine_m(lat, lng, m.lat, m.lng)
        if radius_m == 0 or dist <= radius_m:
            out.append({"device_id": d.id, "merchant_name": m.name, "category": m.category, "lat": m.lat,
                        "lng": m.lng, "distance_m": round(dist), "online": hub.online(d.id)})
    out.sort(key=lambda x: x["distance_m"])
    return {"count": len(out), "online": sum(1 for x in out if x["online"]), "soundboxes": out}


# ------------------------------------------------------------------ campaigns

class CampaignIn(BaseModel):
    kind: str = Field("audio", pattern="^audio$")
    name: str = Field(..., min_length=2, max_length=120)
    prompt: str = Field(..., min_length=3, max_length=1000)
    lang: str = Field("en", pattern=languages.PATTERN)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    radius_m: int = Field(500, ge=0, le=50_000)
    target_categories: list[str] = Field(default_factory=list, max_length=20)
    sku_keywords: list[str] = Field(default_factory=list, max_length=20)
    bid_paise: int = Field(..., gt=0, le=1_000_000)
    tag_bid_paise: int | None = Field(None, gt=0, le=1_000_000)  # sponsor tag; default 75% of bid_paise
    daily_cap_paise: int = Field(0, ge=0, le=100_000_000)
    deploy: bool = True


class CampaignPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    status: str | None = Field(None, pattern="^(active|paused)$")
    bid_paise: int | None = Field(None, gt=0, le=1_000_000)
    tag_bid_paise: int | None = Field(None, gt=0, le=1_000_000)
    daily_cap_paise: int | None = Field(None, ge=0, le=100_000_000)
    radius_m: int | None = Field(None, ge=0, le=50_000)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


class RegenIn(BaseModel):
    prompt: str | None = Field(None, min_length=3, max_length=1000)
    lang: str | None = Field(None, pattern=languages.PATTERN)


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    q = select(Campaign).order_by(Campaign.created_at.desc())
    if user.role == "advertiser":
        q = q.where(Campaign.advertiser_id == user.advertiser_id)
    elif user.role != "admin":
        raise HTTPException(403, "Not allowed for this account")
    return [campaign_dict(db, c) for c in db.scalars(q)]


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    aid = _own_adv(user)
    adv = _adv(db, aid)
    try:
        creative.moderate(body.prompt)
    except creative.CreativeRejected as e:
        raise HTTPException(422, str(e))
    data = body.model_dump()
    deploy = data.pop("deploy")
    _check_tag_price(data["bid_paise"], data["tag_bid_paise"])
    if data["lat"] is None:
        data["lat"], data["lng"] = adv.lat, adv.lng
    if data["kind"] == "audio" and data["radius_m"] and data["lat"] is None:
        raise HTTPException(422, "Set a location for the geofence (or radius 0 for anywhere)")
    data["target_categories"] = [c.strip().lower() for c in data["target_categories"] if c.strip()]
    data["sku_keywords"] = [k.strip().lower() for k in data["sku_keywords"] if k.strip()]
    c = Campaign(id=new_id("CMP", 3), advertiser_id=aid, status="generating", deploy_on_ready=deploy, **data)
    db.add(c)
    db.commit()
    creative.generate_async(c.id)
    return campaign_dict(db, c)


def _check_tag_price(bid: int, tag: int | None) -> None:
    if tag is not None and tag >= bid:
        raise HTTPException(422, "The sponsor tag must cost less than the full ad")


def _camp(db: Session, cid: str, user: User, write: bool = False) -> Campaign:
    c = db.get(Campaign, cid)
    if not c:
        raise HTTPException(404, "campaign not found")
    auth.ensure_advertiser(user, c.advertiser_id, write=write)
    return c


@router.get("/campaigns/{cid}")
def get_campaign(cid: str, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    return campaign_dict(db, _camp(db, cid, user))


@router.patch("/campaigns/{cid}")
def patch_campaign(cid: str, body: CampaignPatch, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    c = _camp(db, cid, user, write=True)
    data = body.model_dump(exclude_unset=True)
    if "bid_paise" in data or "tag_bid_paise" in data:
        _check_tag_price(data.get("bid_paise", c.bid_paise), data.get("tag_bid_paise", c.tag_bid_paise))
    if "status" in data:
        if c.status in ("generating", "failed"):
            raise HTTPException(409, f"Campaign is {c.status}; regenerate it first")
        if data["status"] == "active" and c.kind == "audio" and not (c.creative and c.creative.audio_hash):
            raise HTTPException(409, "This ad has no voice-over yet; regenerate it before going live")
        if data["status"] == "active" and not kyc.can_go_live(db, c.advertiser):
            c.status, c.deploy_on_ready = "pending_kyc", True
            db.commit()
            raise HTTPException(409, "Not live yet: " + "; ".join(kyc.blockers(db, c.advertiser))
                                + ". It goes live automatically once these are done.")
    for k, v in data.items():
        setattr(c, k, v)
    if data.get("status") == "active":
        c.deploy_on_ready = True
    db.commit()
    if data.get("status") == "active" and c.creative and c.creative.audio_hash:
        hub.broadcast_cache_audio(c.creative.audio_hash)
    hub.emit("campaign_update", campaign_id=cid, status=c.status)
    return campaign_dict(db, c)


@router.post("/campaigns/{cid}/regenerate")
def regenerate(cid: str, body: RegenIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    c = _camp(db, cid, user, write=True)
    if c.status == "generating":
        raise HTTPException(409, "Already generating")
    if body.prompt:
        try:
            creative.moderate(body.prompt)
        except creative.CreativeRejected as e:
            raise HTTPException(422, str(e))
    c.deploy_on_ready = c.status in ("active", "pending_kyc")
    c.status, c.error = "generating", None
    db.commit()
    creative.generate_async(cid, body.prompt, body.lang)
    return campaign_dict(db, c)


# ------------------------------------------------------------------ offer claims (public)

@router.get("/offers/{crid}/claim", response_class=HTMLResponse)
def claim_offer(crid: str, d: str | None = Query(None, max_length=32), db: Session = Depends(get_db)):
    cr = db.get(Creative, crid)
    if not cr:
        raise HTTPException(404, "offer not found")
    db.add(Claim(creative_id=crid, device_id=d))
    db.commit()
    hub.emit("offer_claim", creative_id=crid, device_id=d)
    b = cr.banner or {}
    adv = cr.campaign.advertiser
    esc = lambda s: html.escape(str(s or ""))  # noqa: E731
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offer claimed</title><style>body{{margin:0;font-family:system-ui,sans-serif;background:{esc(b.get('bg','#002970'))};
color:{esc(b.get('fg','#fff'))};display:grid;place-items:center;min-height:100vh;text-align:center;padding:16px}}
.c{{max-width:420px}}h1{{font-size:2rem;margin:.2em 0}}.tag{{display:inline-block;background:{esc(b.get('accent','#00BAF2'))};
color:#000;padding:.4em .9em;border-radius:999px;font-weight:700}}</style></head><body><div class="c">
<div class="tag">Offer claimed</div><h1>{esc(b.get('title'))}</h1><p style="font-size:1.25rem">{esc(b.get('subtitle'))}</p>
<p>Show this screen at {esc(adv.name)}{(' · ' + esc(adv.address)) if adv.address else ''}.<br>Code <b>{esc(crid)}</b></p></div></body></html>"""
