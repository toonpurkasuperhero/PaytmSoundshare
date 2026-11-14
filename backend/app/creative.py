"""Generative creative engine: advertiser brief -> 2-3 s audio ad + counter banner.

PRIMARY: Gemini writes and compliance-checks the copy; Gemini TTS voices it.
FALLBACK (only when an AI call fails, with the reason recorded on the creative):
template copy and Microsoft Edge neural voices.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from dataclasses import dataclass

from sqlalchemy import select

from . import audio, languages, llm, sarvam
from .config import AUDIO_DIR, settings
from .db import session_scope
from .hub import hub
from .models import Campaign, Creative
from .money import new_id

log = logging.getLogger("zeromdr.creative")

EDGE_VOICES = {"en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural", "bn": "bn-IN-TanishaaNeural",
               "ta": "ta-IN-PallaviNeural", "te": "te-IN-ShrutiNeural", "kn": "kn-IN-SapnaNeural",
               "ml": "ml-IN-SobhanaNeural", "mr": "mr-IN-AarohiNeural", "gu": "gu-IN-DhwaniNeural"}
PALETTES = {
    "fitness": ("#0B1F3A", "#FFFFFF", "#00E5A8"),
    "healthcare": ("#073B4C", "#FFFFFF", "#FFD166"),
    "bakery": ("#5A2A27", "#FFF4E6", "#FFB703"),
    "food": ("#3D0C02", "#FFFFFF", "#F4A261"),
    "appliance": ("#7A0019", "#FFFFFF", "#FFC300"),
    "electronics": ("#1B1B3A", "#FFFFFF", "#00BAF2"),
    "education": ("#1D3557", "#FFFFFF", "#A8DADC"),
    "beauty": ("#4A1942", "#FFFFFF", "#F7B2D9"),
    "grocery": ("#1B4332", "#FFFFFF", "#95D5B2"),
}
DEFAULT_PALETTE = ("#002970", "#FFFFFF", "#00BAF2")
BANNED = ["guaranteed cure", "100% cure", "cures ", "lose 10 kg", "risk free returns", "no side effects",
          "guaranteed returns", "double your money"]
MAX_SCRIPT_WORDS = 12
# An ad must never sound like a payment confirmation (it plays right after one).
PAYMENT_WORDS = re.compile(r"\b(received|receive|payment|paid|paytm|soundbox|transaction|upi)\b"
                           r"|प्राप्त|भुगतान|पेटीएम", re.I)
VOICE_STYLES = {
    "en": ("a warm, cheerful Indian woman with a clear Indian English accent, quick and crisp, "
           "like a 3-second Indian FM radio spot"),
    "hi": ("a warm, cheerful Indian woman speaking natural everyday Hindi, quick and crisp, "
           "like a 3-second Indian FM radio spot"),
}
for _c, _l in languages.LANGS.items():
    VOICE_STYLES.setdefault(_c, f"a warm, cheerful Indian woman speaking natural everyday {_l['name']}, quick and "
                                "crisp, like a 3-second Indian FM radio spot")

COPY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "script": {"type": "STRING", "description": "spoken ad, max 12 words, must name the advertiser"},
        "title": {"type": "STRING", "description": "banner title, max 22 chars, plain ASCII English"},
        "subtitle": {"type": "STRING", "description": "the offer, max 40 chars, plain ASCII English"},
        "cta": {"type": "STRING", "description": "call to action, max 16 chars, plain ASCII English"},
        "compliant": {"type": "BOOLEAN"},
        "compliance_note": {"type": "STRING"},
    },
    "required": ["script", "title", "subtitle", "cta", "compliant", "compliance_note"],
}


class CreativeRejected(ValueError):
    pass


@dataclass
class Copy:
    script: str
    banner: dict
    source: str
    fallback_reason: str | None
    model: str | None


def moderate(text: str) -> None:
    low = f" {text.lower()} "
    hits = [b.strip() for b in BANNED if b in low]
    if hits:
        raise CreativeRejected(f"Ad makes unverifiable claims: {', '.join(hits)}")


def _ascii(s: str, limit: int) -> str:
    s = s.encode("ascii", "ignore").decode().strip()
    return re.sub(r"\s+", " ", s)[:limit].strip()


def _clean_offer(prompt: str) -> str:
    p = prompt.strip().rstrip(".!")
    if ":" in p:
        p = p.split(":", 1)[1]
    p = re.sub(r"^(please\s+)?(run|create|make|start|promote|announce)\s+(a|an|my|our)?\s*"
               r"([\w-]+\s+){0,3}?(promotion|promo|offer|ad|campaign|sale)\s*(for|of|on|with)?\s*", "", p.strip(), flags=re.I)
    p = re.sub(r"\s+", " ", p).strip(" ,-")
    return p[:1].upper() + p[1:] if p else "Special offer nearby"


def _template_copy(name: str, prompt: str, kind: str) -> tuple[str, str, str, str]:
    offer = _clean_offer(prompt)
    script = f"{name}: {' '.join(offer.split()[:MAX_SCRIPT_WORDS - 2])}!"
    return script, name[:22], offer[:40], ("Scan to claim" if kind == "audio" else "Sponsored by")


def write_copy(name: str, category: str, prompt: str, lang: str, kind: str) -> Copy:
    moderate(prompt)
    bg, fg, accent = PALETTES.get(category, DEFAULT_PALETTE)
    language = languages.describe(lang)
    setting = ("CONTEXT: a payment Soundbox at some OTHER shop has just said the customer's payment was received. "
               "Your ad plays right after that, as a separate short radio-style spot for a nearby business. "
               "The listener is that shop's customer, not the advertiser's.\n"
               "Write a 2-3 second spoken ad" if kind == "audio" else
               "CONTEXT: this brand is sponsoring the payment fee at a shop. Write a short sponsor line")
    base = (
        f"You are the copywriter for Paytm AdPulse. {setting} for the advertiser below.\n"
        f"Advertiser: {name} (category: {category}).\nAdvertiser's brief: \"{prompt}\"\n\n"
        f"Rules: script is spoken in {language}, at most {MAX_SCRIPT_WORDS} words, names the advertiser, "
        "and states the offer from the brief without inventing new terms, prices or dates. "
        "The script must NOT mention payments, money received, the shop, Paytm or the Soundbox. "
        "title, subtitle and cta are plain ASCII English for a small device screen. "
        "Set compliant=false (with compliance_note) if the brief makes health cures, guaranteed financial "
        "returns, illegal, adult, alcohol/tobacco or misleading claims; otherwise compliant=true and "
        "compliance_note=\"ok\"."
    )
    try:
        out, note = None, ""
        for _ in range(2):
            out = llm.generate_json(base + note, schema=COPY_SCHEMA, temperature=0.6, task="ad_copy")
            if not isinstance(out, dict):
                raise llm.AIError("copy response was not an object")
            if not out.get("compliant", True):
                raise CreativeRejected(f"AI compliance check: {out.get('compliance_note') or 'not allowed'}")
            if not PAYMENT_WORDS.search(str(out.get("script", ""))):
                break
            note = (f"\n\nYour previous script was: \"{out.get('script')}\". It wrongly referred to a payment. "
                    "Rewrite it about the advertiser's offer only.")
        else:
            raise llm.AIError("AI script kept referring to the payment")
        script = re.sub(r"\s+", " ", str(out["script"])).strip()
        words = script.split()
        if len(words) > MAX_SCRIPT_WORDS + 4:
            script = " ".join(words[:MAX_SCRIPT_WORDS + 2])
        t_title, t_sub, t_cta = (_template_copy(name, prompt, kind)[1:])
        title = _ascii(str(out.get("title", "")), 22) or t_title
        subtitle = _ascii(str(out.get("subtitle", "")), 40) or t_sub
        cta = _ascii(str(out.get("cta", "")), 16) or t_cta
        source, reason, model = "ai", None, llm.last_model()
    except llm.AIError as e:
        script, title, subtitle, cta = _template_copy(name, prompt, kind)
        source, reason, model = "fallback", str(e), None
    moderate(script + " " + subtitle)
    return Copy(script, {"title": title, "subtitle": subtitle, "cta": cta, "bg": bg, "fg": fg, "accent": accent},
                source, reason, model)


@dataclass
class Voice:
    audio_hash: str | None
    duration_ms: int | None
    voice: str | None
    source: str | None
    fallback_reason: str | None


def _edge_tts(script: str, lang: str) -> tuple[str, int]:
    import edge_tts

    voice = EDGE_VOICES.get(lang, EDGE_VOICES["en"])
    h = hashlib.sha1(f"edge|{voice}|{script}".encode()).hexdigest()
    path = AUDIO_DIR / f"{h}.mp3"
    if not (path.exists() and path.stat().st_size > 0):
        tmp = path.with_suffix(".part")

        async def _run():
            await edge_tts.Communicate(script, voice, rate="+20%").save(str(tmp))

        asyncio.run(_run())
        if tmp.stat().st_size == 0:
            raise RuntimeError("empty audio")
        tmp.replace(path)
    return h, int(path.stat().st_size * 8 / 48_000 * 1000)  # 48 kbps MP3


def _ai_voice(provider: str, script: str, lang: str) -> Voice:
    """One AI voice attempt (sarvam | gemini), cached by content hash. Raises on failure."""
    if provider == "sarvam":
        voice = sarvam.voice_name(lang, "ad")
        key = f"sarvam|{voice}|{lang}|{script}"
    else:
        voice = f"gemini {settings.gemini_tts_voice}"
        style = VOICE_STYLES.get(lang, VOICE_STYLES["en"])
        key = f"gemini|{settings.gemini_tts_model}|{settings.gemini_tts_voice}|{style}|{script}"
    h = hashlib.sha1(key.encode()).hexdigest()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path, meta = AUDIO_DIR / f"{h}.mp3", AUDIO_DIR / f"{h}.ms"
    if path.exists() and meta.exists():
        return Voice(h, int(meta.read_text()), voice, "ai", None)
    if provider == "sarvam":
        pcm, rate = sarvam.tts(script, lang, "ad")
    else:
        pcm, rate = llm.tts(script, VOICE_STYLES.get(lang, VOICE_STYLES["en"]), settings.gemini_tts_voice)
    pcm = audio.trim_and_normalize(pcm, rate)
    path.write_bytes(audio.to_mp3(pcm, rate))
    dur = audio.duration_ms(pcm, rate)
    meta.write_text(str(dur))
    return Voice(h, dur, voice, "ai", None)


def voice_over(script: str, lang: str) -> Voice:
    """AI voices first (Sarvam for Indian languages, Gemini as the AI backup, or the reverse per
    AD_VOICE_PRIMARY); Edge only if every AI voice fails."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    order = ["sarvam", "gemini"] if settings.ad_voice_primary == "sarvam" else ["gemini", "sarvam"]
    if lang not in ("en", "hi") and "sarvam" in order:  # Sarvam is the specialist for regional languages
        order = ["sarvam"] + [p for p in order if p != "sarvam"]
    errors = []
    for provider in order:
        if provider == "sarvam" and not sarvam.configured():
            continue
        if provider == "gemini" and not llm.configured():
            continue
        try:
            v = _ai_voice(provider, script, lang)
            if errors:  # an AI backup served it: still AI, but say what failed first
                v.fallback_reason = "; ".join(errors)
            return v
        except (llm.AIError, sarvam.SarvamError) as e:
            errors.append(f"{provider}: {e}")
        except Exception as e:  # encoding problems etc.
            log.exception("voice post-processing failed")
            errors.append(f"{provider}: audio processing failed: {e}")
    reason = "; ".join(errors) or "no AI voice configured (set SARVAM_API_KEY or GEMINI_API_KEY)"
    if settings.tts_fallback == "edge" and lang not in EDGE_VOICES:
        reason = f"{reason}; no backup voice for {languages.LANGS.get(lang, {}).get('name', lang)}"
    elif settings.tts_fallback == "edge":
        try:
            eh, dur = _edge_tts(script, lang)
            return Voice(eh, dur, EDGE_VOICES.get(lang, EDGE_VOICES["en"]), "fallback", reason)
        except Exception as e2:
            reason = f"{reason}; edge fallback failed: {e2}"
    return Voice(None, None, None, None, reason)


# ------------------------------------------------------------------ campaign jobs

def generate(campaign_id: str, prompt: str | None = None, lang: str | None = None) -> None:
    """Build (or rebuild) a campaign's creative. Runs in a worker thread."""
    try:
        with session_scope() as db:
            c = db.get(Campaign, campaign_id)
            if not c:
                return
            if prompt:
                c.prompt = prompt
            if lang:
                c.lang = lang
            name, category, brief, lang_, kind = c.advertiser.name, c.advertiser.category, c.prompt, c.lang, c.kind
        cp = write_copy(name, category, brief, lang_, kind)
        v = voice_over(cp.script, lang_) if kind == "audio" else Voice(None, None, None, None, None)
        with session_scope() as db:
            c = db.get(Campaign, campaign_id)
            cr = c.creative or Creative(id=new_id("CR"), campaign_id=c.id, lang=lang_, script="", banner={})
            if not c.creative:
                db.add(cr)
            cr.lang, cr.script, cr.banner = lang_, cp.script, cp.banner
            cr.source, cr.fallback_reason, cr.model = cp.source, cp.fallback_reason, cp.model
            cr.audio_hash, cr.duration_ms, cr.voice = v.audio_hash, v.duration_ms, v.voice
            cr.voice_source, cr.voice_fallback_reason = v.source, v.fallback_reason
            if kind == "audio" and not v.audio_hash:
                c.status, c.error = "failed", f"Could not create the voice-over: {v.fallback_reason}"
            else:
                c.status, c.error = ("active" if c.deploy_on_ready else "draft"), None
            status = c.status
        if v.audio_hash and status == "active":
            hub.broadcast_cache_audio(v.audio_hash)
        hub.emit("campaign_update", campaign_id=campaign_id, status=status)
    except CreativeRejected as e:
        _fail(campaign_id, str(e))
    except Exception as e:
        log.exception("creative generation failed for %s", campaign_id)
        _fail(campaign_id, f"Unexpected error: {e}")


def _fail(campaign_id: str, msg: str) -> None:
    with session_scope() as db:
        c = db.get(Campaign, campaign_id)
        if c:
            c.status, c.error = "failed", msg
    hub.emit("campaign_update", campaign_id=campaign_id, status="failed", reason=msg)


def generate_async(campaign_id: str, prompt: str | None = None, lang: str | None = None) -> None:
    threading.Thread(target=generate, args=(campaign_id, prompt, lang), daemon=True).start()


def backfill_audio() -> int:
    """Re-voice live audio creatives whose MP3 is missing (e.g. media/ wiped). Startup task."""
    todo = []
    with session_scope() as db:
        for c in db.scalars(select(Campaign).where(Campaign.kind == "audio",
                                                   Campaign.status.in_(("active", "paused", "draft")))):
            cr = c.creative
            if cr and (not cr.audio_hash or not (AUDIO_DIR / f"{cr.audio_hash}.mp3").exists()):
                todo.append((c.id, cr.script, cr.lang))
    for cid, script, lang in todo:
        def job(cid=cid, script=script, lang=lang):
            v = voice_over(script, lang)
            with session_scope() as db:
                cr = db.get(Campaign, cid).creative
                cr.audio_hash, cr.duration_ms, cr.voice = v.audio_hash, v.duration_ms, v.voice
                cr.voice_source, cr.voice_fallback_reason = v.source, v.fallback_reason
        threading.Thread(target=job, daemon=True).start()
    return len(todo)
