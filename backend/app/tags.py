"""Sponsor tags: the short line played after the payment message in busy hours.

    "Sponsored by FitZone Gym."   /   "FitZone Gym की ओर से।"

Spoken in the payment-announcement voice (Sarvam) so it sounds like part of the Soundbox,
then Gemini TTS, then Edge, each only if the previous fails. Cached per (language, sponsor).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading

from . import audio, languages, llm, sarvam
from .config import AUDIO_DIR

log = logging.getLogger("zeromdr.tags")
TEMPLATES = {"en": "Sponsored by {name}.", "hi": "{name} की ओर से।"}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _text(name: str, lang: str) -> str:
    if lang in TEMPLATES or not sarvam.configured():
        return TEMPLATES.get(lang, TEMPLATES["en"]).format(name=name)
    try:
        return sarvam.translate(f"Sponsored by {name}.", lang, mode="formal")
    except sarvam.SarvamError as e:
        log.warning("sponsor tag translation for %s failed (%s); using English", lang, e)
        return TEMPLATES["en"].format(name=name)


def _speak(text: str, lang: str) -> tuple[bytes, int, str]:
    errors = []
    if sarvam.configured():
        try:
            pcm, rate = sarvam.tts(text, lang, "announce")
            return pcm, rate, sarvam.voice_name(lang, "announce")
        except sarvam.SarvamError as e:
            errors.append(f"sarvam: {e}")
    if llm.configured():
        try:
            pcm, rate = llm.tts(text, "a calm, clear Indian female announcer, brief", None)
            return pcm, rate, "gemini"
        except llm.AIError as e:
            errors.append(f"gemini: {e}")
    raise RuntimeError("; ".join(errors) or "no AI voice configured")


def ensure(name: str, lang: str) -> tuple[str, int]:
    """(audio_hash, duration_ms) of the sponsor tag MP3 in media/audio. Raises on failure."""
    lang = lang if lang in languages.LANGS else "en"
    key = hashlib.sha1(f"tag|{lang}|{name}".encode()).hexdigest()
    mp3, meta = AUDIO_DIR / f"{key}.mp3", AUDIO_DIR / f"{key}.json"
    if mp3.exists() and meta.exists():
        return key, json.loads(meta.read_text(encoding="utf-8"))["duration_ms"]
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if mp3.exists() and meta.exists():
            return key, json.loads(meta.read_text(encoding="utf-8"))["duration_ms"]
        text = _text(name, lang)
        pcm, rate, voice = _speak(text, lang)
        pcm = audio.trim_and_normalize(pcm, rate, pad_ms=40, target_peak=0.85)
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(audio.to_mp3(pcm, rate, kbps=64))
        dur = audio.duration_ms(pcm, rate)
        meta.write_text(json.dumps({"text": text, "voice": voice, "duration_ms": dur}, ensure_ascii=False),
                        encoding="utf-8")
        return key, dur


def prewarm(name: str, lang: str) -> None:
    def job():
        try:
            ensure(name, lang)
        except Exception as e:  # noqa: BLE001 - background best effort
            log.warning("sponsor tag prewarm %s/%s failed: %s", lang, name, e)
    threading.Thread(target=job, daemon=True).start()
