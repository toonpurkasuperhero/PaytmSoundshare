"""Google Gemini client: the PRIMARY path for ad copy, voice, bill parsing and division.

Callers catch `AIError` and use their deterministic fallback ONLY then, recording
the reason so the UI can show "Fallback: <reason>".
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings

log = logging.getLogger("zeromdr.ai")
BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {500, 502, 503, 504}
IST = timezone(timedelta(hours=5, minutes=30))


class AIError(RuntimeError):
    pass


@dataclass
class AIHealth:
    calls: int = 0
    failures: int = 0
    last_ok_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    models: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def ok(self) -> None:
        with self._lock:
            self.calls += 1
            self.last_ok_at = datetime.now(timezone.utc)

    def fail(self, msg: str) -> None:
        with self._lock:
            self.calls += 1
            self.failures += 1
            self.last_error = msg[:300]
            self.last_error_at = datetime.now(timezone.utc)

    def as_dict(self) -> dict:
        return {"configured": configured(), "text_model": settings.gemini_model,
                "fallback_models": [m for m in _model_chain()[1:]], "tts_model": settings.gemini_tts_model,
                "quota_exhausted_until": quota_state(),
                "voice": settings.gemini_tts_voice, "calls": self.calls, "failures": self.failures,
                "last_ok_at": self.last_ok_at, "last_error": self.last_error, "last_error_at": self.last_error_at,
                "models": self.models}


health = AIHealth()


def configured() -> bool:
    return bool(settings.gemini_api_key)


def _headers() -> dict:
    return {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}


class QuotaExhausted(AIError):
    def __init__(self, msg: str, retry_s: float):
        super().__init__(msg)
        self.retry_s = retry_s


_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?")


def _retry_delay_s(err: dict) -> float | None:
    """google.rpc.RetryInfo.retryDelay ("30s") or the "Please retry in 17h46m19s" text."""
    for d in err.get("details") or []:
        if str(d.get("@type", "")).endswith("RetryInfo") and d.get("retryDelay"):
            try:
                return float(str(d["retryDelay"]).rstrip("s"))
            except ValueError:
                pass
    m = re.search(r"retry in ([\dhms.]+)", err.get("message", ""))
    if m:
        dm = _DUR.fullmatch(m.group(1).rstrip("."))
        if dm and any(dm.groups()):
            h, mi, s = dm.groups()
            return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    return None


def _short(msg: str) -> str:
    return msg.split("\n")[0].split(". For more information")[0][:220]


def _request(method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
    """One Gemini HTTP call. Retries once on transient 5xx/network errors and on short
    rate limits; never retries an exhausted (daily) quota."""
    if not configured():
        raise AIError("GEMINI_API_KEY is not set")
    timeout = timeout or settings.gemini_timeout_s
    last = ""
    for attempt in range(2):
        try:
            r = httpx.request(method, BASE + path, json=body, headers=_headers(), timeout=timeout)
        except httpx.HTTPError as e:
            last = f"network error: {e.__class__.__name__}"
        else:
            if r.status_code < 300:
                return r.json()
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            last = _short(f"HTTP {r.status_code} {err.get('status', '')}: {err.get('message', '')}".strip())
            if r.status_code == 429:
                delay = _retry_delay_s(err)
                if delay is None or delay > 5 or attempt == 1:
                    raise QuotaExhausted(last, delay if delay is not None else 60.0)
                time.sleep(delay)
                continue
            if r.status_code not in RETRY_STATUS:
                break
        if attempt == 0:
            time.sleep(1.5)
    raise AIError(last)


# Per-model circuit breaker: a model whose quota is exhausted is skipped until it resets.
_blocked_until: dict[str, float] = {}
_block_lock = threading.Lock()


def _model_chain() -> list[str]:
    chain = [settings.gemini_model] + [m.strip() for m in settings.gemini_fallback_models.split(",") if m.strip()]
    return list(dict.fromkeys(chain))


def _available(model: str) -> bool:
    with _block_lock:
        until = _blocked_until.get(model)
        if until and until > time.time():
            return False
        _blocked_until.pop(model, None)
        return True


def _block(model: str, seconds: float) -> None:
    with _block_lock:
        _blocked_until[model] = time.time() + max(30.0, seconds)


def quota_state() -> dict:
    now = time.time()
    with _block_lock:
        return {m: datetime.fromtimestamp(t, timezone.utc) for m, t in _blocked_until.items() if t > now}


_local = threading.local()


def last_model() -> str | None:
    """The Gemini model that served the most recent successful call on this thread."""
    return getattr(_local, "model", None)


# ------------------------------------------------------------------ text / multimodal → JSON

def inline_part(data: bytes, mime: str) -> dict:
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}


def generate_json(prompt: str, schema: dict | None = None, parts: list[dict] | None = None,
                  temperature: float = 0.3, task: str = "generate") -> dict | list:
    """Structured output from Gemini. Raises AIError on any failure (network, quota,
    safety block, malformed JSON) so the caller can fall back explicitly."""
    gen_cfg: dict = {"responseMimeType": "application/json", "temperature": temperature}
    if schema:
        gen_cfg["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}, *(parts or [])]}],
            "generationConfig": gen_cfg}
    errors: list[str] = []
    for model in _model_chain():
        if not _available(model):
            errors.append(f"{model}: quota exhausted until "
                          f"{quota_state()[model].astimezone(IST):%d %b %H:%M} IST")
            continue
        try:
            out = _generate_once(model, body)
        except QuotaExhausted as e:
            _block(model, e.retry_s)
            errors.append(f"{model}: {e}")
            continue
        except AIError as e:
            # Overload / unknown model: try the next model; bad output: also try the next one.
            errors.append(f"{model}: {e}")
            continue
        _local.model = model
        health.ok()
        if errors:
            log.info("AI %s served by %s after: %s", task, model, "; ".join(errors))
        return out
    msg = "; ".join(errors) or "no Gemini model configured"
    health.fail(f"{task}: {msg}")
    log.warning("AI %s failed: %s", task, msg)
    raise AIError(msg)


def _generate_once(model: str, body: dict) -> dict | list:
    data = _request("POST", f"/models/{model}:generateContent", body)
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise AIError(f"Gemini returned no output ({reason})")
    cand = cands[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    if not text:
        raise AIError(f"Gemini returned empty output (finishReason={cand.get('finishReason')})")
    try:
        return json.loads(text)
    except ValueError as e:
        raise AIError(f"Gemini returned invalid JSON: {e}") from e


def transcribe(audio: bytes, mime: str, lang: str) -> str:
    from . import languages
    hint = "Indian English" if lang == "en" else f"{languages.describe(lang)} (code-mixed with English is fine)"
    out = generate_json(
        f"Transcribe this voice note exactly as spoken. Expected language: {hint}. "
        "It is a shop owner describing a promotion for their business. Do not add anything.",
        schema={"type": "OBJECT", "properties": {"text": {"type": "STRING"}}, "required": ["text"]},
        parts=[inline_part(audio, mime)], temperature=0.0, task="transcribe")
    text = str(out.get("text", "")).strip() if isinstance(out, dict) else ""
    if not text:
        raise AIError("transcription was empty")
    return text


# ------------------------------------------------------------------ speech (TTS)

def _find_audio_b64(obj) -> tuple[str, str] | None:
    """Locate the first base64 audio payload in an Interactions / generateContent response."""
    if isinstance(obj, dict):
        mime = obj.get("mime_type") or obj.get("mimeType") or ""
        data = obj.get("data")
        if isinstance(data, str) and len(data) > 100 and ("audio" in mime or not mime):
            return data, mime
        for v in obj.values():
            hit = _find_audio_b64(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_audio_b64(v)
            if hit:
                return hit
    return None


def _decode_audio(b64: str, mime: str) -> tuple[bytes, int]:
    raw = base64.b64decode(b64)
    if raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw)) as w:
            if w.getsampwidth() != 2:
                raise AIError(f"unexpected WAV sample width {w.getsampwidth()}")
            pcm = w.readframes(w.getnframes())
            if w.getnchannels() == 2:  # downmix
                import array
                s = array.array("h", pcm)
                pcm = array.array("h", ((s[i] + s[i + 1]) // 2 for i in range(0, len(s), 2))).tobytes()
            return pcm, w.getframerate()
    rate = 24000
    for part in mime.replace(" ", "").split(";"):
        if part.startswith("rate="):
            rate = int(part[5:])
    return raw, rate  # headerless 16-bit LE PCM


def tts(text: str, style: str, voice: str | None = None) -> tuple[bytes, int]:
    """Synthesize speech. Returns (mono 16-bit PCM, sample_rate). Raises AIError."""
    voice = voice or settings.gemini_tts_voice
    model = settings.gemini_tts_model
    interactions_body = {
        "model": model,
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata", "style": style}],
        }]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    legacy_body = {
        "contents": [{"parts": [{"text": f"Say in a {style} way: {text}"}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}},
    }
    errors = []
    if not _available(model):
        raise AIError(f"{model}: quota exhausted until {quota_state()[model].astimezone(IST):%d %b %H:%M} IST")
    for path, body in (("/interactions", interactions_body), (f"/models/{model}:generateContent", legacy_body)):
        try:
            data = _request("POST", path, body, timeout=max(settings.gemini_timeout_s, 45))
            hit = _find_audio_b64(data)
            if not hit:
                raise AIError("no audio in response")
            pcm, rate = _decode_audio(*hit)
            if len(pcm) < rate // 5:  # < 0.1 s
                raise AIError("audio too short")
            health.ok()
            return pcm, rate
        except QuotaExhausted as e:
            _block(model, e.retry_s)
            errors.append(f"{path.split(':')[0]}: {e}")
            break
        except AIError as e:
            errors.append(f"{path.split(':')[0]}: {e}")
    msg = "; ".join(errors)
    health.fail(f"tts: {msg}")
    log.warning("AI tts failed: %s", msg)
    raise AIError(msg)


# ------------------------------------------------------------------ model check

def check_models() -> dict:
    """Verify the configured model ids exist for this key (run at startup)."""
    out = {}
    for m in dict.fromkeys([*_model_chain(), settings.gemini_tts_model]):
        try:
            _request("GET", f"/models/{m}", timeout=10)
            out[m] = "ok"
        except AIError as e:
            out[m] = str(e)
    health.models = out
    return out
