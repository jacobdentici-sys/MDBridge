from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import load_settings, save_settings
from .mdblist import MDBListClient
from .nuvio import NuvioClient
from .stremio import StremioClient
from .sync_engine import SyncEngine
from .ui import render_home


engine = SyncEngine()
loop_task: asyncio.Task | None = None
stremio_links: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop_task
    loop_task = asyncio.create_task(engine.background_loop())
    yield
    await engine.stop()
    if loop_task:
        loop_task.cancel()


app = FastAPI(title="MDBridge", version="0.1.1", lifespan=lifespan)


class SettingsBody(BaseModel):
    mdblist_api_key: str | None = None
    tmdb_token: str | None = None
    sync_interval_seconds: int | None = None
    import_nuvio: bool | None = None
    import_stremio: bool | None = None
    push_nuvio: bool | None = None
    push_stremio: bool | None = None


class NuvioBody(BaseModel):
    email: str
    password: str
    profile_id: int = 1


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> str:
    s = load_settings()
    base = str(request.base_url).rstrip("/")
    return render_home(
        mdblist=bool(s.mdblist_api_key),
        tmdb=bool(s.tmdb_token),
        nuvio=bool(s.nuvio_refresh_token),
        stremio=bool(s.stremio_auth_key),
        addon_url=f"{base}/{s.addon_token}/manifest.json",
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    s = load_settings()
    return {
        "mdblist_configured": bool(s.mdblist_api_key),
        "tmdb_configured": bool(s.tmdb_token),
        "nuvio_connected": bool(s.nuvio_refresh_token),
        "nuvio_profile_id": s.nuvio_profile_id,
        "stremio_connected": bool(s.stremio_auth_key),
        "sync_interval_seconds": s.sync_interval_seconds,
        "last_run": engine.last_run.isoformat() if engine.last_run else None,
        "last_error": engine.last_error or None,
        "last_stats": engine.last_stats,
        "stremio_addon_url": f"{str(request.base_url).rstrip('/')}/{s.addon_token}/manifest.json",
    }


@app.post("/api/settings")
async def update_settings(body: SettingsBody) -> dict[str, Any]:
    s = load_settings()
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        if key == "sync_interval_seconds":
            value = max(30, int(value))
        setattr(s, key, value)
    save_settings(s)
    valid = None
    if body.mdblist_api_key is not None:
        valid = await MDBListClient(s.mdblist_api_key).validate()
        if not valid:
            raise HTTPException(400, "MDBList API key validation failed")
    return {"ok": True, "mdblist_valid": valid}


@app.post("/api/nuvio/connect")
async def connect_nuvio(body: NuvioBody) -> dict[str, Any]:
    session = await NuvioClient.sign_in(body.email, body.password)
    profiles = await NuvioClient.profiles(session.access_token)
    indexes = {int(x.get("profile_index") or 0) for x in profiles}
    if body.profile_id not in indexes:
        raise HTTPException(400, f"Nuvio profile {body.profile_id} was not found. Available: {sorted(indexes)}")
    s = load_settings()
    s.nuvio_refresh_token = session.refresh_token
    s.nuvio_profile_id = body.profile_id
    save_settings(s)
    return {"ok": True, "profiles": profiles, "selected_profile": body.profile_id}


@app.post("/api/nuvio/disconnect")
async def disconnect_nuvio() -> dict[str, Any]:
    s = load_settings()
    s.nuvio_refresh_token = ""
    save_settings(s)
    return {"ok": True}


@app.post("/api/stremio/link/start")
async def stremio_link_start() -> dict[str, Any]:
    client = StremioClient()
    result = await client.create_link()
    code = str(result.get("code") or "").upper()
    if not code:
        raise HTTPException(502, "Stremio did not return a link code")
    stremio_links[code] = result
    return {"code": code, "link": result.get("link"), "qrcode": result.get("qrcode")}


@app.get("/api/stremio/link/status/{code}")
async def stremio_link_status(code: str) -> dict[str, Any]:
    client = StremioClient()
    auth_key = await client.read_link(code)
    if not auth_key:
        return {"authorized": False}
    if not await client.validate(auth_key):
        raise HTTPException(502, "Stremio authorization key validation failed")
    s = load_settings()
    s.stremio_auth_key = auth_key
    save_settings(s)
    stremio_links.pop(code.upper(), None)
    return {"authorized": True}


@app.post("/api/stremio/disconnect")
async def disconnect_stremio() -> dict[str, Any]:
    s = load_settings()
    s.stremio_auth_key = ""
    save_settings(s)
    return {"ok": True}


@app.post("/api/sync")
async def sync_now() -> dict[str, Any]:
    try:
        return await engine.sync_once()
    except Exception as exc:
        engine.last_error = str(exc)
        raise HTTPException(502, str(exc)) from exc


@app.get("/{token}/manifest.json")
async def manifest(token: str) -> dict[str, Any]:
    check_addon_token(token)
    return {
        "id": "community.mdbridge",
        "version": "0.1.1",
        "name": "MDBridge",
        "description": "MDBList-backed Continue Watching catalogs. Tracking is performed by the MDBridge companion service.",
        "resources": ["catalog"],
        "types": ["movie", "series"],
        "catalogs": [
            {"type": "movie", "id": "mdbridge-continue-movie", "name": "MDBList Continue Watching"},
            {"type": "series", "id": "mdbridge-continue-series", "name": "MDBList Continue Watching"},
        ],
        "behaviorHints": {"configurable": False},
    }


@app.get("/{token}/catalog/{media_type}/{catalog_id}.json")
async def catalog(token: str, media_type: str, catalog_id: str) -> dict[str, Any]:
    check_addon_token(token)
    expected = "mdbridge-continue-movie" if media_type == "movie" else "mdbridge-continue-series"
    if media_type not in {"movie", "series"} or catalog_id != expected:
        return {"metas": []}
    if not engine.cached_playback:
        s = load_settings()
        if s.mdblist_api_key:
            engine.cached_playback = await MDBListClient(s.mdblist_api_key).playback()
    items = sorted(engine.cached_playback.values(), key=lambda x: x.updated_at, reverse=True)
    ids: list[str] = []
    for item in items:
        if media_type == "movie" and item.key.kind != "movie":
            continue
        if media_type == "series" and item.key.kind != "episode":
            continue
        if item.key.imdb not in ids:
            ids.append(item.key.imdb)
    metas = []
    for imdb in ids[:30]:
        meta = await cinemeta_preview(media_type, imdb)
        if meta:
            metas.append(meta)
    return {"metas": metas}


def check_addon_token(token: str) -> None:
    if token != load_settings().addon_token:
        raise HTTPException(404, "Not found")


async def cinemeta_preview(media_type: str, imdb: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"https://v3-cinemeta.strem.io/meta/{media_type}/{imdb}.json")
            response.raise_for_status()
            meta = response.json().get("meta") or {}
        return {
            "id": imdb,
            "type": media_type,
            "name": meta.get("name") or imdb,
            "poster": meta.get("poster"),
            "background": meta.get("background"),
            "description": meta.get("description"),
            "releaseInfo": meta.get("releaseInfo"),
        }
    except Exception:
        return {"id": imdb, "type": media_type, "name": imdb}
