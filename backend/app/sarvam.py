"""Sarvam AI client: Indian-language voices (Bulbul TTS) and translation (Mayura).

Used for: payment announcements in the merchant's language, and ad voice-overs.
Docs: https://docs.sarvam.ai (auth header `api-subscription-key`).
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time
import wave
from datetime import datetime, timezone

import httpx

from . import languages
from .config import settings

log = logging.getLogger("zeromdr.sarvam")
BASE = "https://api.sarvam.ai"

# bulbul:v4-flash has purpose-built "ads" personas for some languages; everything else uses v3.
AD_VOICES_V4 = {"en": "simran_en_ads", "hi": "ishita_hi_ads"}


class SarvamError(RuntimeError):
    pass


class _Health:
    def __init__(self) -> None:
        self.calls = 0
        self.failures = 0
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        self._lock = threading.Lock()

    def ok(self) -> None:
        with self._lock:
            self.calls += 1
            self.last_ok_at = datetime.now(timezone.utc)

    def fail(self, msg: str) -> None:
        with self._lock:
            self.calls += 1
            self.failures += 1
            self.last_error, self.last_error_at = msg[:300], datetime.now(timezone.utc)

    def as_dict(self) -> dict:
        return {"configured": configured(), "announce_voice": f"{settings.sarvam_announce_model}/"
                f"{settings.sarvam_announce_speaker}", "ad_voices": {**AD_VOICES_V4, "*": f"{settings.sarvam_ad_model}/"
                f"{settings.sarvam_ad_speaker}"}, "calls": self.calls, "failures": self.failures,
                "last_ok_at": self.last_ok_at, "last_error": self.last_error, "last_error_at": self.last_error_at}


health = _Health()


def configured() -> bool:
    return bool(settings.sarvam_api_key)


def _post(path: str, body: dict, timeout: float = 25.0) -> dict:
    if not configured():
        raise SarvamError("SARVAM_API_KEY is not set")
    last = ""
    for attempt in range(2):
        try:
            r = httpx.post(BASE + path, json=body, timeout=timeout,
                           headers={"api-subscription-key": settings.sarvam_api_key})
        except httpx.HTTPError as e:
            last = f"network error: {e.__class__.__name__}"
        else:
            if r.status_code < 300:
                return r.json()
            try:
                err = r.json().get("error") or r.json()
                last = f"HTTP {r.status_code} {err.get('code', '')}: {err.get('message', '') or err.get('detail', '')}"
            except ValueError:
                last = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504) or "quota" in last:
                break
        if attempt == 0:
            time.sleep(1.2)
    raise SarvamError(last[:300])


def _voice(lang: str, purpose: str) -> tuple[str, str, float]:
    if purpose == "ad" and lang in AD_VOICES_V4:
        return "bulbul:v4-flash", AD_VOICES_V4[lang], 1.05
    if purpose == "ad":
        return settings.sarvam_ad_model, settings.sarvam_ad_speaker, 1.05
    return settings.sarvam_announce_model, settings.sarvam_announce_speaker, settings.sarvam_announce_pace


def voice_name(lang: str, purpose: str) -> str:
    model, speaker, _ = _voice(lang, purpose)
    return f"sarvam {model} {speaker}"


def tts(text: str, lang: str, purpose: str = "ad") -> tuple[bytes, int]:
    """Speak `text` in `lang`. Returns (mono 16-bit PCM, sample_rate). Raises SarvamError."""
    model, speaker, pace = _voice(lang, purpose)
    body = {"text": text, "language_code": languages.bcp47(lang), "model": model, "speaker": speaker,
            "pace": pace, "speech_sample_rate": 24000, "output_audio_codec": "wav"}
    try:
        try:
            data = _post("/text-to-speech", body)
        except SarvamError as e:
            if "language_code" not in str(e) and "target_language_code" not in str(e):
                raise
            body["target_language_code"] = body.pop("language_code")  # older API field name
            data = _post("/text-to-speech", body)
        audios = data.get("audios") or []
        if not audios:
            raise SarvamError("no audio returned")
        raw = base64.b64decode(audios[0])
        with wave.open(io.BytesIO(raw)) as w:
            if w.getsampwidth() != 2:
                raise SarvamError(f"unexpected sample width {w.getsampwidth()}")
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
            if w.getnchannels() == 2:
                import array
                s = array.array("h", pcm)
                pcm = array.array("h", ((s[i] + s[i + 1]) // 2 for i in range(0, len(s), 2))).tobytes()
    except SarvamError as e:
        health.fail(f"tts[{lang}/{purpose}]: {e}")
        log.warning("Sarvam TTS %s/%s failed: %s", lang, purpose, e)
        raise
    except (wave.Error, ValueError) as e:
        health.fail(f"tts[{lang}/{purpose}]: bad audio {e}")
        raise SarvamError(f"bad audio: {e}") from e
    health.ok()
    return pcm, rate


def translate(text: str, target: str, source: str = "en", mode: str = "formal") -> str:
    body = {"input": text, "source_language_code": languages.bcp47(source),
            "target_language_code": languages.bcp47(target), "model": "mayura:v1",
            "mode": mode, "speaker_gender": "Female", "numerals_format": "international"}
    try:
        out = str(_post("/translate", body).get("translated_text") or "").strip()
        if not out:
            raise SarvamError("empty translation")
    except SarvamError as e:
        health.fail(f"translate[{target}]: {e}")
        raise
    health.ok()
    return out
