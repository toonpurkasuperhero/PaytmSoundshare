"""WebSockets: /ws/device/{id} (ESP32 + simulator) and /ws/admin (dashboards)."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import adx, auth, settlement
from ..db import session_scope
from ..hub import REPLACED, device_url, hub
from ..models import Device, utcnow

router = APIRouter()
log = logging.getLogger("zeromdr.ws")
PING_EVERY_S = 20


def _auth(device_id: str, token: str) -> bool:
    with session_scope() as db:
        d = db.get(Device, device_id)
        return bool(d and token and d.token_hash == auth.sha256(token))


def _is_admin(token: str) -> bool:
    with session_scope() as db:
        u = auth.user_from_token(db, token)
        return bool(u and u.role == "admin")


def _on_hello(device_id: str, msg: dict) -> list[dict]:
    cached = set(msg.get("cache") or [])
    with session_scope() as db:
        d = db.get(Device, device_id)
        d.fw = str(msg.get("fw") or d.fw or "")[:20]
        d.last_seen = utcnow()
        m = d.merchant
        out: list[dict] = [
            {"type": "hello_ack", "deviceId": device_id,
             "merchant": {"id": m.id, "name": m.name, "lang": m.lang},
             "serverTime": int(utcnow().timestamp())},
            {"type": "idle", "banners": adx.idle_banners(db, m)},
        ]
        for h, _ in adx.cacheable_audio(db, m):
            if h not in cached:
                out.append({"type": "cache_audio", "hash": h, "url": device_url(device_id, f"/media/audio/{h}.mp3")})
        out += settlement.device_resume_messages(db, device_id)
        return out


def _on_heartbeat(device_id: str, msg: dict) -> None:
    with session_scope() as db:
        d = db.get(Device, device_id)
        d.last_seen = utcnow()
        if msg.get("fw"):
            d.fw = str(msg["fw"])[:20]
        if isinstance(msg.get("rssi"), (int, float)):
            d.rssi = int(msg["rssi"])


async def _pump(ws: WebSocket, q: asyncio.Queue) -> None:
    while True:
        text = await q.get()
        if text == REPLACED:
            await ws.send_text('{"type":"replaced","reason":"This Soundbox was connected from another window or device"}')
            await ws.close(code=4000)
            return
        await ws.send_text(text)


async def _pinger(q: asyncio.Queue) -> None:
    while True:
        await asyncio.sleep(PING_EVERY_S)
        q.put_nowait('{"type":"ping"}')


@router.websocket("/ws/device/{device_id}")
async def device_ws(ws: WebSocket, device_id: str, token: str = ""):
    if not await asyncio.to_thread(_auth, device_id, token):
        await ws.close(code=1008)
        return
    await ws.accept()
    # Behind a TLS proxy/tunnel (Cloudflare, Caddy) use the public scheme + host the device came through.
    host = ws.headers.get("x-forwarded-host") or ws.headers.get("host")
    scheme = "https" if ws.headers.get("x-forwarded-proto", "").split(",")[0].strip() in ("https", "wss") else "http"
    q = hub.add_device(device_id, f"{scheme}://{host}" if host else None)
    hub.emit("device_status", device_id=device_id, online=True)
    tasks = [asyncio.create_task(_pump(ws, q)), asyncio.create_task(_pinger(q))]
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get("type")
            if t == "hello":
                for m in await asyncio.to_thread(_on_hello, device_id, msg):
                    q.put_nowait(json.dumps(m, separators=(",", ":"), default=str))
            elif t == "heartbeat":
                await asyncio.to_thread(_on_heartbeat, device_id, msg)
            elif t == "play_ack":
                await asyncio.to_thread(settlement.play_ack, device_id, msg)
            elif t == "cache_ok":
                hub.emit("device_cache", device_id=device_id, hash=msg.get("hash"))
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: closed by us (replaced)
        pass
    except Exception:
        log.exception("device socket %s crashed", device_id)
    finally:
        for t in tasks:
            t.cancel()
        hub.remove_device(device_id, q)
        hub.emit("device_status", device_id=device_id, online=hub.online(device_id))


@router.websocket("/ws/admin")
async def admin_ws(ws: WebSocket, token: str = ""):
    if not await asyncio.to_thread(_is_admin, token):
        await ws.close(code=1008)
        return
    await ws.accept()
    q = hub.add_admin()
    pump = asyncio.create_task(_pump(ws, q))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        hub.remove_admin(q)
