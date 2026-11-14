"""PCM post-processing for ad voice-overs: trim silence, normalise, encode MP3 for the ESP32."""
from __future__ import annotations

import array
import sys

import lameenc

SILENCE_DBFS = -42.0
PAD_MS = 60
TARGET_PEAK = 0.89  # ≈ -1 dBFS


def _samples(pcm: bytes) -> array.array:
    s = array.array("h")
    s.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder == "big":
        s.byteswap()
    return s


def trim_and_normalize(pcm: bytes, rate: int, pad_ms: int = PAD_MS, target_peak: float = TARGET_PEAK) -> bytes:
    s = _samples(pcm)
    if not s:
        return pcm
    thresh = int(32767 * 10 ** (SILENCE_DBFS / 20))
    start = next((i for i, v in enumerate(s) if abs(v) > thresh), 0)
    end = next((i for i in range(len(s) - 1, -1, -1) if abs(s[i]) > thresh), len(s) - 1)
    pad = rate * pad_ms // 1000
    s = s[max(0, start - pad): min(len(s), end + pad)]
    peak = max((abs(v) for v in s), default=0)
    if peak > 0:
        gain = min(4.0, target_peak * 32767 / peak)
        s = array.array("h", (max(-32768, min(32767, int(v * gain))) for v in s))
    if sys.byteorder == "big":
        s.byteswap()
    return s.tobytes()


def duration_ms(pcm: bytes, rate: int) -> int:
    return (len(pcm) // 2) * 1000 // rate


def to_mp3(pcm: bytes, rate: int, kbps: int = 48) -> bytes:
    enc = lameenc.Encoder()
    enc.set_bit_rate(kbps)
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(2)
    return bytes(enc.encode(pcm) + enc.flush())
