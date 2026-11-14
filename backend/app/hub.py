"""Real-time fan-out to devices (ESP32 / simulator) and admin dashboards.

Every public method is thread-safe: business logic runs in worker threads
(sync endpoints, poller) while sockets live on the asyncio loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

log = logging.getLogger("zeromdr.hub")
REPLACED = "__replaced__"  # sentinel: tells a superseded device socket to close


class Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._devices: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._admins: set[asyncio.Queue] = set()
        self._device_base: dict[str, str] = {}

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    # ---- registration (called on the loop) ----
    def add_device(self, device_id: str, base_url: str | None = None) -> asyncio.Queue:
        """A Soundbox id is ONE physical box: a new connection replaces any older one
        (otherwise two windows/devices both play every payment, overlapping)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        for old in list(self._devices[device_id]):
            self._devices[device_id].discard(old)
            self._put(old, REPLACED)
        self._devices[device_id].add(q)
        if base_url:
            self._device_base[device_id] = base_url
        return q

    def device_base(self, device_id: str | None) -> str | None:
        """http://host:port exactly as this device reached the server (always reachable from it)."""
        return self._device_base.get(device_id) if device_id else None

    def remove_device(self, device_id: str, q: asyncio.Queue) -> None:
        self._devices[device_id].discard(q)

    def add_admin(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._admins.add(q)
        return q

    def remove_admin(self, q: asyncio.Queue) -> None:
        self._admins.discard(q)

    def online(self, device_id: str) -> bool:
        return bool(self._devices.get(device_id))

    def online_ids(self) -> list[str]:
        return [d for d, qs in self._devices.items() if qs]

    # ---- sending (any thread) ----
    def _put(self, q: asyncio.Queue, text: str) -> None:
        try:
            q.put_nowait(text)
        except asyncio.QueueFull:
            log.warning("queue full, dropping message")

    def _dispatch(self, queues: list[asyncio.Queue], payload: dict) -> None:
        if not self.loop or not queues:
            return
        text = json.dumps(payload, separators=(",", ":"), default=str)
        for q in queues:
            self.loop.call_soon_threadsafe(self._put, q, text)

    def send_device(self, device_id: str | None, msg: dict) -> bool:
        if not device_id:
            return False
        queues = list(self._devices.get(device_id, ()))
        self._dispatch(queues, msg)
        if queues:
            self.emit("device_msg", device_id=device_id, msg_type=msg.get("type"))
        return bool(queues)

    def broadcast_devices(self, msg: dict) -> None:
        for qs in list(self._devices.values()):
            self._dispatch(list(qs), msg)

    def broadcast_cache_audio(self, audio_hash: str) -> None:
        """Tell every connected device to cache an ad, with a URL each device can reach."""
        for device_id, qs in list(self._devices.items()):
            if qs:
                self._dispatch(list(qs), {"type": "cache_audio", "hash": audio_hash,
                                          "url": device_url(device_id, f"/media/audio/{audio_hash}.mp3")})

    def emit(self, event_type: str, **data) -> None:
        self._dispatch(list(self._admins), {"type": event_type, **data})


hub = Hub()


def device_url(device_id: str | None, path: str) -> str:
    """Absolute URL for a device: the address it connected on, else the server's public base URL."""
    from .config import settings
    return (hub.device_base(device_id) or settings.base_url) + path


def public_url(device_id: str | None, path: str) -> str:
    """URL a CUSTOMER'S PHONE must open (offer QR): never localhost."""
    from .config import settings
    base = hub.device_base(device_id) or ""
    if not base or "localhost" in base or "127.0.0.1" in base:
        base = settings.base_url
    return base + path
