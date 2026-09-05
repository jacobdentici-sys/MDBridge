from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .models import MediaKey, ProgressItem, WatchedItem, parse_time
from .tmdb import TMDBClient

BASE = "https://api.nuvio.tv"
PUBLISHABLE_KEY = "sb_publishable_1Clq8rlTVACkdcZuqr6_AD__xUUC_EN"


@dataclass(slots=True)
class Session:
    access_token: str
    refresh_token: str


class NuvioClient:
    def __init__(self, tmdb: TMDBClient):
        self.tmdb = tmdb

    @staticmethod
    def public_headers() -> dict[str, str]:
        return {"apikey": PUBLISHABLE_KEY, "Content-Type": "application/json"}

    @classmethod
    async def sign_in(cls, email: str, password: str) -> Session:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{BASE}/auth/v1/token",
                params={"grant_type": "password"},
                headers=cls.public_headers(),
                json={"email": email, "password": password},
            )
            response.raise_for_status()
            payload = response.json()
        return Session(str(payload["access_token"]), str(payload["refresh_token"]))

    @classmethod
    async def refresh(cls, refresh_token: str) -> Session:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{BASE}/auth/v1/token",
                params={"grant_type": "refresh_token"},
                headers=cls.public_headers(),
                json={"refresh_token": refresh_token},
            )
            response.raise_for_status()
            payload = response.json()
        return Session(str(payload["access_token"]), str(payload["refresh_token"]))

    @classmethod
    async def _rpc(cls, access_token: str, name: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {**cls.public_headers(), "Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{BASE}/rest/v1/rpc/{name}", headers=headers, json=payload or {})
            response.raise_for_status()
            return response.json() if response.content else None

    @classmethod
    async def profiles(cls, access_token: str) -> list[dict[str, Any]]:
        data = await cls._rpc(access_token, "sync_pull_profiles")
        return data if isinstance(data, list) else []

    @classmethod
    async def pull_raw(cls, access_token: str, profile_id: int) -> dict[str, list[dict[str, Any]]]:
        watched: list[dict[str, Any]] = []
        page = 1
        while True:
            rows = await cls._rpc(
                access_token,
                "sync_pull_watched_items",
                {"p_profile_id": profile_id, "p_page": page, "p_page_size": 500},
            )
            rows = rows if isinstance(rows, list) else []
            watched.extend(rows)
            if len(rows) < 500:
                break
            page += 1
        progress = await cls._rpc(
            access_token,
            "sync_pull_watch_progress",
            {"p_profile_id": profile_id, "p_limit": 200},
        )
        return {
            "watched": watched,
            "progress": progress if isinstance(progress, list) else [],
        }

    async def normalize(self, raw: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, WatchedItem], dict[str, ProgressItem]]:
        watched: dict[str, WatchedItem] = {}
        progress: dict[str, ProgressItem] = {}
        for row in raw.get("watched", []):
            key = await self._key_from_row(row)
            if not key:
                continue
            item = WatchedItem(
                key=key,
                watched_at=parse_time(row.get("watched_at") or row.get("last_watched")),
                title=str(row.get("title") or row.get("name") or ""),
                source="nuvio",
            )
            watched[key.stable_id] = item
        for row in raw.get("progress", []):
            key = await self._key_from_row(row)
            if not key:
                continue
            try:
                position = max(0, int(row.get("position") or 0))
                duration = max(0, int(row.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration <= 0 or position <= 0:
                continue
            item = ProgressItem(
                key=key,
                percent=100.0 * position / duration,
                updated_at=parse_time(row.get("last_watched")),
                duration_ms=duration,
                position_ms=position,
                title=str(row.get("title") or row.get("name") or ""),
                source="nuvio",
            ).normalized()
            progress[key.stable_id] = item
        return watched, progress

    async def _key_from_row(self, row: dict[str, Any]) -> MediaKey | None:
        content_type = str(row.get("content_type") or "").lower()
        content_id = str(row.get("content_id") or "")
        kind = "movie" if content_type == "movie" else "episode"
        imdb = content_id if content_id.startswith("tt") else ""
        if not imdb and content_id.startswith("tmdb:"):
            try:
                tmdb_id = int(content_id.split(":", 1)[1])
                imdb = await self.tmdb.imdb_from_tmdb(tmdb_id, "movie" if kind == "movie" else "series") or ""
            except (ValueError, httpx.HTTPError):
                return None
        if not imdb.startswith("tt"):
            return None
        if kind == "movie":
            return MediaKey("movie", imdb)
        try:
            season = int(row.get("season"))
            episode = int(row.get("episode"))
        except (TypeError, ValueError):
            video_id = str(row.get("video_id") or "")
            parts = video_id.split(":")
            if len(parts) < 3:
                return None
            try:
                season, episode = int(parts[-2]), int(parts[-1])
            except ValueError:
                return None
        return MediaKey("episode", imdb, season, episode)

    @classmethod
    async def push_watched(cls, access_token: str, profile_id: int, items: list[WatchedItem]) -> None:
        payload: list[dict[str, Any]] = []
        for item in items:
            base = {
                "content_id": item.key.imdb,
                "content_type": "movie" if item.key.kind == "movie" else "series",
                "title": item.title or item.key.imdb,
                "watched_at": int(item.watched_at.timestamp() * 1000),
            }
            if item.key.kind == "episode":
                base.update({"season": item.key.season, "episode": item.key.episode})
            payload.append(base)
        for start in range(0, len(payload), 500):
            await cls._rpc(
                access_token,
                "sync_push_watched_items",
                {"p_profile_id": profile_id, "p_items": payload[start:start+500]},
            )

    @classmethod
    async def push_progress(cls, access_token: str, profile_id: int, items: list[ProgressItem]) -> None:
        payload: list[dict[str, Any]] = []
        for item in items:
            if not item.duration_ms or not item.position_ms:
                continue
            base = {
                "content_id": item.key.imdb,
                "content_type": "movie" if item.key.kind == "movie" else "series",
                "video_id": item.key.imdb if item.key.kind == "movie" else f"{item.key.imdb}:{item.key.season}:{item.key.episode}",
                "position": int(item.position_ms),
                "duration": int(item.duration_ms),
                "last_watched": int(item.updated_at.timestamp() * 1000),
            }
            if item.key.kind == "episode":
                base.update({"season": item.key.season, "episode": item.key.episode})
            payload.append(base)
        for start in range(0, len(payload), 500):
            await cls._rpc(
                access_token,
                "sync_push_watch_progress",
                {"p_profile_id": profile_id, "p_entries": payload[start:start+500]},
            )
