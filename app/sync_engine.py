from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from .config import load_settings, save_settings
from .mdblist import MDBListClient
from .models import ProgressItem, WatchedItem
from .nuvio import NuvioClient
from .stremio import StremioClient
from .tmdb import TMDBClient

log = logging.getLogger("mdbridge.sync")


class SyncEngine:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.last_run: datetime | None = None
        self.last_error: str = ""
        self.last_stats: dict[str, Any] = {}
        self.cached_playback: dict[str, ProgressItem] = {}
        self.cached_watched: dict[str, WatchedItem] = {}
        self._stop = asyncio.Event()

    async def background_loop(self) -> None:
        while not self._stop.is_set():
            settings = load_settings()
            if settings.mdblist_api_key and settings.tmdb_token:
                try:
                    await self.sync_once()
                except Exception as exc:
                    self.last_error = str(exc)
                    log.exception("MDBridge background sync failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=max(30, settings.sync_interval_seconds))

    async def stop(self) -> None:
        self._stop.set()

    async def sync_once(self) -> dict[str, Any]:
        if self.lock.locked():
            return {"status": "busy"}
        async with self.lock:
            settings = load_settings()
            if not settings.mdblist_api_key:
                raise RuntimeError("MDBList API key is not configured")
            if not settings.tmdb_token:
                raise RuntimeError("TMDB Read Access Token is not configured")

            mdblist = MDBListClient(settings.mdblist_api_key)
            tmdb = TMDBClient(settings.tmdb_token)
            nuvio = NuvioClient(tmdb)
            stremio = StremioClient()

            mb_watched, mb_progress = await asyncio.gather(mdblist.watched(), mdblist.playback())
            nuvio_watched: dict[str, WatchedItem] = {}
            nuvio_progress: dict[str, ProgressItem] = {}
            stremio_watched: dict[str, WatchedItem] = {}
            stremio_progress: dict[str, ProgressItem] = {}
            nuvio_session = None

            if settings.nuvio_refresh_token and (settings.import_nuvio or settings.push_nuvio):
                # Nuvio refresh tokens rotate and are single use. Persist the replacement immediately.
                nuvio_session = await NuvioClient.refresh(settings.nuvio_refresh_token)
                settings.nuvio_refresh_token = nuvio_session.refresh_token
                save_settings(settings)
                raw = await NuvioClient.pull_raw(nuvio_session.access_token, settings.nuvio_profile_id)
                nuvio_watched, nuvio_progress = await nuvio.normalize(raw)

            if settings.stremio_auth_key and (settings.import_stremio or settings.push_stremio):
                items = await stremio.get_items(settings.stremio_auth_key)
                stremio_watched, stremio_progress = await stremio.normalize(items)

            imported_watched: list[WatchedItem] = []
            if settings.import_nuvio:
                imported_watched += [x for k, x in nuvio_watched.items() if k not in mb_watched]
            if settings.import_stremio:
                imported_watched += [x for k, x in stremio_watched.items() if k not in mb_watched]
            imported_watched = newest_watched(imported_watched)
            if imported_watched:
                await mdblist.add_watched(imported_watched)
                for item in imported_watched:
                    mb_watched[item.key.stable_id] = WatchedItem(
                        item.key, item.watched_at, item.title, "mdblist"
                    )
                    if item.key.stable_id in mb_progress:
                        await mdblist.clear_progress(item.key)
                        mb_progress.pop(item.key.stable_id, None)

            imported_progress = 0
            remote_progress: dict[str, ProgressItem] = {}
            if settings.import_nuvio:
                merge_newer_progress(remote_progress, nuvio_progress)
            if settings.import_stremio:
                merge_newer_progress(remote_progress, stremio_progress)
            for stable_id, remote in remote_progress.items():
                if stable_id in mb_watched:
                    continue
                current = mb_progress.get(stable_id)
                if current is None or is_remote_newer(remote, current):
                    # Avoid tiny startup offsets creating noisy Continue Watching entries.
                    if remote.percent < 1.0:
                        continue
                    await mdblist.set_progress(remote)
                    mb_progress[stable_id] = ProgressItem(
                        key=remote.key,
                        percent=remote.percent,
                        updated_at=remote.updated_at,
                        duration_ms=remote.duration_ms,
                        position_ms=remote.position_ms,
                        title=remote.title,
                        source="mdblist",
                        tmdb_id=remote.tmdb_id,
                    ).normalized()
                    imported_progress += 1

            # MDBList playback returns percentage but not runtime. Resolve runtime through TMDB
            # so Nuvio and Stremio receive actual millisecond positions.
            active_progress: list[ProgressItem] = []
            for stable_id, item in mb_progress.items():
                if stable_id in mb_watched:
                    continue
                if not item.duration_ms:
                    try:
                        item.duration_ms = await tmdb.duration_ms(item.key, item.tmdb_id)
                    except Exception as exc:
                        log.warning("Could not resolve duration for %s: %s", stable_id, exc)
                if item.duration_ms:
                    item.position_ms = int(item.duration_ms * item.percent / 100.0)
                if item.position_ms and item.duration_ms:
                    active_progress.append(item.normalized())

            pushed_nuvio_watched = pushed_stremio_watched = 0
            pushed_nuvio_progress = pushed_stremio_progress = 0
            if settings.push_nuvio and nuvio_session:
                delta = [x for k, x in mb_watched.items() if k not in nuvio_watched]
                progress_delta = [
                    x
                    for x in active_progress
                    if progress_needs_push(x, nuvio_progress.get(x.key.stable_id))
                ]
                if delta:
                    await NuvioClient.push_watched(nuvio_session.access_token, settings.nuvio_profile_id, delta)
                if progress_delta:
                    await NuvioClient.push_progress(
                        nuvio_session.access_token,
                        settings.nuvio_profile_id,
                        progress_delta,
                    )
                pushed_nuvio_watched = len(delta)
                pushed_nuvio_progress = len(progress_delta)

            if settings.push_stremio and settings.stremio_auth_key:
                delta = [x for k, x in mb_watched.items() if k not in stremio_watched]
                progress_delta = [
                    x
                    for x in active_progress
                    if progress_needs_push(x, stremio_progress.get(x.key.stable_id))
                ]
                # merge_into_account preserves Stremio fields and no-ops unchanged records.
                await stremio.merge_into_account(
                    settings.stremio_auth_key,
                    delta,
                    progress_delta,
                )
                pushed_stremio_watched = len(delta)
                pushed_stremio_progress = len(progress_delta)

            self.cached_playback = mb_progress
            self.cached_watched = mb_watched
            self.last_run = datetime.now(UTC)
            self.last_error = ""
            self.last_stats = {
                "mdblist_watched": len(mb_watched),
                "mdblist_playback": len(mb_progress),
                "imported_watched": len(imported_watched),
                "imported_progress": imported_progress,
                "nuvio_watched_seen": len(nuvio_watched),
                "stremio_watched_seen": len(stremio_watched),
                "pushed_nuvio_watched": pushed_nuvio_watched,
                "pushed_stremio_watched": pushed_stremio_watched,
                "pushed_nuvio_progress": pushed_nuvio_progress,
                "pushed_stremio_progress": pushed_stremio_progress,
                "active_progress_pushed": len(active_progress),
            }
            return {"status": "ok", **self.last_stats}


def newest_watched(items: list[WatchedItem]) -> list[WatchedItem]:
    by_key: dict[str, WatchedItem] = {}
    for item in items:
        current = by_key.get(item.key.stable_id)
        if current is None or item.watched_at > current.watched_at:
            by_key[item.key.stable_id] = item
    return list(by_key.values())


def merge_newer_progress(target: dict[str, ProgressItem], source: dict[str, ProgressItem]) -> None:
    for stable_id, item in source.items():
        current = target.get(stable_id)
        if current is None or item.updated_at > current.updated_at:
            target[stable_id] = item


def is_remote_newer(remote: ProgressItem, current: ProgressItem) -> bool:
    # Timestamp is primary. If clocks are nearly tied, a meaningful percentage difference wins.
    delta = (remote.updated_at - current.updated_at).total_seconds()
    if delta > 5:
        return True
    if delta >= -5 and abs(remote.percent - current.percent) >= 1.0:
        return remote.percent > current.percent
    return False


def progress_needs_push(canonical: ProgressItem, remote: ProgressItem | None) -> bool:
    """Avoid rewriting an unchanged provider progress row every polling cycle."""
    if remote is None:
        return True
    return abs(canonical.percent - remote.percent) >= 0.5
