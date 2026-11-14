"""Generate the Soundbox announcement clips (Paytm-Soundbox style).

    [chime] "Received" <amount> "rupees" "on Paytm"
    [chime] "पेटीएम पर" <amount> "रुपये" "प्राप्त हुए"

Tokens (docs/API_CONTRACT.md §3), files <token>.wav: chime, pre, n0..n99, hundred, thousand, lakh, crore, rupees, received.
Each spoken clip is trimmed to ~10 ms of silence, peak-normalised and stored as 24 kHz mono WAV:
MP3 would add ~50-70 ms of encoder padding to both ends of every clip, which makes stitched
announcements sound gappy. The chime is synthesised here (our own two-tone sound).

Output: backend/media/clips/<lang>/ (browser simulator) and firmware/data/clips/<lang>/ (ESP32 LittleFS).
Usage (repo root):  backend\\.venv\\Scripts\\python tools\\gen_clips.py [--force]
Then flash:         pio run -d firmware -t uploadfs
"""
from __future__ import annotations

import argparse
import array
import asyncio
import math
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import edge_tts
import miniaudio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import audio  # noqa: E402

RATE = 24000
OUTS = [ROOT / "backend" / "media" / "clips", ROOT / "firmware" / "data" / "clips"]
VOICES = {"en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural"}
WORDS = {
    "en": {"pre": "Received", "hundred": "hundred", "thousand": "thousand", "lakh": "lakh", "crore": "crore",
           "rupees": "rupees", "received": "on Paytm"},
    "hi": {"pre": "पेटीएम पर", "hundred": "सौ", "thousand": "हज़ार", "lakh": "लाख", "crore": "करोड़",
           "rupees": "रुपये", "received": "प्राप्त हुए"},
}


def tokens(lang: str) -> dict[str, str]:
    t = {f"n{i}": str(i) for i in range(100)}  # neural voices read numerals in their locale
    t.update(WORDS[lang])
    return t


def chime_pcm() -> bytes:
    """Bright two-note notification chime (E6 -> A6) with a soft bell decay, ~0.45 s."""
    out = array.array("h")
    for freq, dur in ((1318.5, 0.13), (1760.0, 0.32)):
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            env = min(1.0, i / (RATE * 0.004)) * math.exp(-t * (9 if dur < 0.2 else 6))
            v = (math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(2 * math.pi * 2 * freq * t)
                 + 0.12 * math.sin(2 * math.pi * 3 * freq * t)) * env
            out.append(int(max(-1, min(1, v * 0.62)) * 32767))
    out.extend([0] * int(RATE * 0.12))  # breath before the voice
    return out.tobytes()


def mp3_to_pcm(data: bytes) -> bytes:
    dec = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=RATE)
    return dec.samples.tobytes()


def to_wav(pcm: bytes) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


async def make_clip(text: str, voice: str, tmp: Path) -> bytes:
    raw = tmp / "raw.mp3"
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, voice, rate="+22%").save(str(raw))
            break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1 + attempt)
    pcm = audio.trim_and_normalize(mp3_to_pcm(raw.read_bytes()), RATE, pad_ms=10, target_peak=0.85)
    return to_wav(pcm)


async def gen_lang(lang: str, force: bool) -> tuple[int, int]:
    primary = OUTS[0] / lang
    primary.mkdir(parents=True, exist_ok=True)
    made = 0
    sem = asyncio.Semaphore(6)

    async def one(tok: str, text: str):
        nonlocal made
        path = primary / f"{tok}.wav"
        if path.exists() and path.stat().st_size > 0 and not force:
            return
        async with sem:
            with tempfile.TemporaryDirectory() as td:
                try:
                    path.write_bytes(await make_clip(text, VOICES[lang], Path(td)))
                    made += 1
                except Exception as e:
                    print(f"  ! {lang}/{tok}: {e}")

    await asyncio.gather(*(one(k, v) for k, v in tokens(lang).items()))
    chime = primary / "chime.wav"
    if force or not chime.exists():
        chime.write_bytes(to_wav(chime_pcm()))
        made += 1
    for out in OUTS:  # drop superseded MP3 clips (they would be used as a gappy fallback)
        for old in (out / lang).glob("*.mp3"):
            old.unlink()
    for extra in OUTS[1:]:  # mirror to the firmware filesystem image
        dst = extra / lang
        dst.mkdir(parents=True, exist_ok=True)
        for f in primary.glob("*.wav"):
            shutil.copy2(f, dst / f.name)
    return made, len(list(primary.glob("*.wav")))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="regenerate existing clips")
    a = ap.parse_args()
    for lang in ("en", "hi"):
        made, total = await gen_lang(lang, a.force)
        size = sum(f.stat().st_size for f in (OUTS[0] / lang).glob("*.wav"))
        print(f"{lang}: generated {made}, {total} clips, {size / 1024:.0f} KiB")


if __name__ == "__main__":
    asyncio.run(main())
