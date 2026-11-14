"""SoundShare backend entrypoint.

Run:  .venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import auth, creative, llm, migrate, settlement
from .config import AUDIO_DIR, MEDIA_DIR, SIM_DIR, WEB_DIST_DIR, settings
from .db import Base, engine
from .hub import hub
from .routers import ads, core, ops, ws
from .routers import auth as auth_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("zeromdr")


async def _background_loop() -> None:
    while True:
        await asyncio.sleep(settings.poll_interval_s)
        for job in (settlement.poll_once, settlement.expire_legs, settlement.release_stale_holds):
            try:
                await asyncio.to_thread(job)
            except Exception:
                log.exception("background job %s failed", job.__name__)


def _startup_checks() -> None:
    if not llm.configured():
        log.warning("GEMINI_API_KEY is not set: ad copy, voice and bill division will use fallbacks")
        return
    for model, state in llm.check_models().items():
        (log.info if state == "ok" else log.error)("Gemini model %s: %s", model, state)


@asynccontextmanager
async def lifespan(_: FastAPI):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    hub.bind(asyncio.get_running_loop())
    await asyncio.to_thread(Base.metadata.create_all, engine)
    await asyncio.to_thread(migrate.run)
    await asyncio.to_thread(auth.bootstrap_admin)
    asyncio.get_running_loop().run_in_executor(None, _startup_checks)
    n = await asyncio.to_thread(creative.backfill_audio)
    if n:
        log.info("Re-voicing %d creatives with missing audio", n)
    task = asyncio.create_task(_background_loop())
    log.info("SoundShare up. provider=%s (%s) base_url=%s", settings.payment_provider, settings.provider_mode,
             settings.base_url)
    yield
    task.cancel()


app = FastAPI(title="Paytm SoundShare", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth_routes.router)
app.include_router(core.router)
app.include_router(ads.router)
app.include_router(ops.router)
app.include_router(ws.router)


@app.get("/healthz")
def healthz():
    return {"ok": True, "provider": settings.payment_provider}


MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/sim", StaticFiles(directory=SIM_DIR, html=True), name="sim")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Serve the built web app (web/dist) with SPA fallback."""
    if path.startswith(("api/", "ws/", "media/", "sim/")):
        raise HTTPException(404)
    if not WEB_DIST_DIR.exists():
        return {"detail": "Web app not built. Run `npm run build` in web/, or use the Vite dev server.",
                "docs": "/docs"}
    target = (WEB_DIST_DIR / path).resolve()
    if path and target.is_file() and WEB_DIST_DIR.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(WEB_DIST_DIR / "index.html")
