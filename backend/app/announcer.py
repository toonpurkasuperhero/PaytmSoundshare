"""Payment announcements in the merchant's language, spoken as ONE natural sentence.

Why not stitched clips for every language: in Tamil, Telugu, Malayalam etc. numbers fuse
(6,000 is one word), so "6" + "thousand" clips sound wrong. Sarvam speaks the whole sentence:

    [chime] "Received 6,500 rupees on Paytm"      / "पेटीएम पर 6,500 रुपये प्राप्त हुए"

The sentence template per language comes from Sarvam translation once and is saved to
config/announce_templates.json (review/edit it there). Audio is generated when the bill is
created (pre-warm), cached per (language, amount, voice), and served to devices at
/api/announce/<order_id>.mp3. Devices fall back to their local en/hi clips if it isn't available.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import wave
from pathlib import Path

from . import audio, languages, sarvam
from .config import CONFIG_DIR, MEDIA_DIR, settings

log = logging.getLogger("zeromdr.announcer")
TEMPLATES_FILE = CONFIG_DIR / "announce_templates.json"
ANNOUNCE_DIR = MEDIA_DIR / "announce"
CHIME = MEDIA_DIR / "clips" / "en" / "chime.wav"
BUILTIN = {
    "en": "Received {amount} rupees on Paytm",
    "hi": "पेटीएम पर {amount} रुपये प्राप्त हुए",
}
_SAMPLE_AMOUNT = "6,500"
_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def amount_text(paise: int) -> str:
    """650000 -> '6,500' (Indian grouping, paise dropped; Sarvam reads commas correctly)."""
    s = str(max(0, paise // 100))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _load() -> dict:
    try:
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def template(lang: str) -> str | None:
    """Sentence template with {amount}. Built-in for en/hi, translated once for others."""
    with _lock:
        saved = _load()
        if lang in saved:
            return saved[lang]
        if lang in BUILTIN:
            return BUILTIN[lang]
    if not sarvam.configured() or lang not in languages.LANGS:
        return None
    try:
        # Impersonal, formal phrasing: the Soundbox announces a receipt; it isn't "I received".
        out = sarvam.translate(f"{_SAMPLE_AMOUNT} rupees received on Paytm.", lang, mode="formal")
    except sarvam.SarvamError as e:
        log.warning("announcement template for %s unavailable: %s", lang, e)
        return None
    for token in (_SAMPLE_AMOUNT, "6500", "६,५००"):
        if token in out:
            tpl = out.replace(token, "{amount}", 1).rstrip("।. ")
            break
    else:
        log.warning("translation for %s lost the amount (%r); not using it", lang, out)
        return None
    with _lock:
        saved = _load()
        saved[lang] = tpl
        TEMPLATES_FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("announcement template for %s: %s", lang, tpl)
    return tpl


def available(lang: str) -> bool:
    return sarvam.configured() and lang in languages.LANGS


def _chime() -> bytes:
    try:
        with wave.open(str(CHIME)) as w:
            return w.readframes(w.getnframes())
    except (OSError, wave.Error):
        return b""


def ensure(lang: str, paise: int) -> Path:
    """Path to the announcement MP3, generating it if needed. Raises sarvam.SarvamError / RuntimeError."""
    tpl = template(lang)
    if not tpl:
        raise RuntimeError(f"no announcement sentence for language '{lang}'")
    text = tpl.replace("{amount}", amount_text(paise))
    voice = sarvam.voice_name(lang, "announce")
    key = hashlib.sha1(f"{voice}|{settings.sarvam_announce_pace}|{text}".encode()).hexdigest()
    path = ANNOUNCE_DIR / f"{key}.mp3"
    if path.exists() and path.stat().st_size > 0:
        return path
    with _lock:
        klock = _key_locks.setdefault(key, threading.Lock())
    with klock:  # concurrent requests for the same announcement generate it once
        if path.exists() and path.stat().st_size > 0:
            return path
        pcm, rate = sarvam.tts(text, lang, "announce")
        pcm = audio.trim_and_normalize(pcm, rate, pad_ms=30, target_peak=0.85)
        if rate == 24000:
            pcm = _chime() + pcm
        ANNOUNCE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(audio.to_mp3(pcm, rate, kbps=64))
        tmp.replace(path)
    return path


def prewarm(lang: str, paise: int) -> None:
    """Generate in the background when the bill is created, so it's instant at payment time."""
    if not available(lang):
        return

    def job():
        try:
            ensure(lang, paise)
        except Exception as e:  # noqa: BLE001 - background best effort; device falls back to clips
            log.warning("announcement prewarm %s/%s failed: %s", lang, paise, e)
    threading.Thread(target=job, daemon=True).start()
