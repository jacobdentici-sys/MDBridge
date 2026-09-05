from __future__ import annotations

import base64
import re
import zlib
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import MediaKey, ProgressItem, WatchedItem, parse_time

API = "https://api.strem.io/api"
LINK = "https://link.stremio.com/api/v2"
CINEMETA = "https://v3-cinemeta.strem.io"
COLLECTION = "libraryItem"


class StremioClient:
    def __init__(self):
        self._meta_cache: dict[str, dict[str, Any]] = {}

    async def _api(self, path: str, body: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{API}/{path}", json=body)
            response.raise_for_status()
            payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Stremio {path}: {payload['error']}")
        return payload.get("result")

    async def create_link(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{LINK}/create", params={"type": "Create"})
            response.raise_for_status()
            payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result") or {}

    async def read_link(self, code: str) -> str | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{LINK}/read", params={"type": "Read", "code": code.strip().upper()})
            response.raise_for_status()
            payload = response.json()
        if payload.get("error"):
            error = payload["error"]
            # Link flow returns an error until the user approves it.
            if isinstance(error, dict) and int(error.get("code") or 0) == 101:
                return None
            return None
        result = payload.get("result") or {}
        value = str(result.get("authKey") or "")
        return value or None

    async def validate(self, auth_key: str) -> bool:
        try:
            result = await self._api("getUser", {"type": "GetUser", "authKey": auth_key})
            return isinstance(result, dict) and bool(result.get("_id"))
        except Exception:
            return False

    async def get_items(self, auth_key: str) -> list[dict[str, Any]]:
        result = await self._api(
            "datastoreGet",
            {"authKey": auth_key, "collection": COLLECTION, "ids": [], "all": True},
        )
        return [x for x in (result or []) if isinstance(x, dict)]

    async def put_items(self, auth_key: str, changes: list[dict[str, Any]]) -> None:
        if not changes:
            return
        for start in range(0, len(changes), 100):
            result = await self._api(
                "datastorePut",
                {"authKey": auth_key, "collection": COLLECTION, "changes": changes[start:start+100]},
            )
            if not isinstance(result, dict) or result.get("success") is not True:
                raise RuntimeError("Stremio did not acknowledge datastorePut")

    async def cinemeta(self, imdb: str) -> dict[str, Any]:
        if imdb in self._meta_cache:
            return self._meta_cache[imdb]
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(f"{CINEMETA}/meta/series/{imdb}.json")
            response.raise_for_status()
            payload = response.json()
        meta = payload.get("meta") or {}
        self._meta_cache[imdb] = meta
        return meta

    async def normalize(self, items: list[dict[str, Any]]) -> tuple[dict[str, WatchedItem], dict[str, ProgressItem]]:
        watched: dict[str, WatchedItem] = {}
        progress: dict[str, ProgressItem] = {}
        for item in items:
            content_type = str(item.get("type") or "")
            if content_type not in {"movie", "series"}:
                continue
            state = item.get("state") if isinstance(item.get("state"), dict) else {}
            title = str(item.get("name") or item.get("_id") or "")
            imdb = self._series_imdb(item) if content_type == "series" else str(item.get("_id") or "")
            if not imdb.startswith("tt"):
                continue
            watched_at = parse_time(state.get("lastWatched"))
            if content_type == "movie":
                try:
                    count = int(state.get("timesWatched") or 0)
                except (TypeError, ValueError):
                    count = 0
                if count > 0:
                    key = MediaKey("movie", imdb)
                    watched[key.stable_id] = WatchedItem(key, watched_at, title, "stremio")
                p = self._progress_values(state)
                if p:
                    position, duration = p
                    key = MediaKey("movie", imdb)
                    progress[key.stable_id] = ProgressItem(
                        key, 100.0 * position / duration, watched_at, duration, position, title, "stremio"
                    ).normalized()
                continue

            meta = await self.cinemeta(imdb)
            videos = self._videos(meta)
            video_ids = [str(v.get("id")) for v in videos]
            for video_id in decode_watched(state.get("watched"), video_ids):
                parts = video_parts(video_id)
                if not parts:
                    continue
                season, episode = parts
                key = MediaKey("episode", imdb, season, episode)
                watched[key.stable_id] = WatchedItem(key, watched_at, title, "stremio")
            current = str(state.get("video_id") or "")
            parts = video_parts(current)
            p = self._progress_values(state)
            if parts and p:
                position, duration = p
                season, episode = parts
                key = MediaKey("episode", imdb, season, episode)
                progress[key.stable_id] = ProgressItem(
                    key, 100.0 * position / duration, watched_at, duration, position, title, "stremio"
                ).normalized()
        return watched, progress

    async def merge_into_account(
        self,
        auth_key: str,
        watched_items: list[WatchedItem],
        progress_items: list[ProgressItem],
    ) -> None:
        remote = await self.get_items(auth_key)
        by_id = {str(x.get("_id")): x for x in remote if x.get("_id")}
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        candidates: dict[str, dict[str, Any]] = {}
        series_ids = {x.key.imdb for x in watched_items if x.key.kind == "episode"}
        series_ids |= {x.key.imdb for x in progress_items if x.key.kind == "episode"}
        metas = {imdb: await self.cinemeta(imdb) for imdb in series_ids}

        for item in watched_items:
            content_id = item.key.imdb
            candidate = dict(candidates.get(content_id) or by_id.get(content_id) or new_item(item, now))
            state = {**default_state(), **(candidate.get("state") or {})}
            if item.key.kind == "movie":
                state["timesWatched"] = max(1, int(state.get("timesWatched") or 0))
                state["lastWatched"] = item.watched_at.isoformat().replace("+00:00", "Z")
            else:
                videos = self._videos(metas.get(content_id, {}))
                video_ids = [str(v.get("id")) for v in videos]
                watched_set = decode_watched(state.get("watched"), video_ids)
                target = find_video(videos, item.key.season, item.key.episode)
                if target:
                    watched_set.add(str(target.get("id")))
                    state["watched"] = encode_watched(watched_set, video_ids)
                    state["lastWatched"] = item.watched_at.isoformat().replace("+00:00", "Z")
            candidate["state"] = state
            candidates[content_id] = candidate

        for item in progress_items:
            if not item.position_ms or not item.duration_ms:
                continue
            content_id = item.key.imdb
            candidate = dict(candidates.get(content_id) or by_id.get(content_id) or new_item(item, now))
            state = {**default_state(), **(candidate.get("state") or {})}
            state["timeOffset"] = int(item.position_ms)
            state["duration"] = int(item.duration_ms)
            state["lastWatched"] = item.updated_at.isoformat().replace("+00:00", "Z")
            if item.key.kind == "movie":
                state["video_id"] = content_id
            else:
                videos = self._videos(metas.get(content_id, {}))
                target = find_video(videos, item.key.season, item.key.episode)
                state["video_id"] = str(target.get("id")) if target else f"{content_id}:{item.key.season}:{item.key.episode}"
            candidate["state"] = state
            candidates[content_id] = candidate

        changes: list[dict[str, Any]] = []
        for content_id, candidate in candidates.items():
            candidate.setdefault("_ctime", now)
            candidate["_mtime"] = now
            candidate.setdefault("removed", False)
            candidate.setdefault("temp", True)
            candidate.setdefault("behaviorHints", {})
            if compact_compare(candidate) != compact_compare(by_id.get(content_id) or {}):
                changes.append(candidate)
        await self.put_items(auth_key, changes)

    @staticmethod
    def _videos(meta: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            [x for x in (meta.get("videos") or []) if isinstance(x, dict) and x.get("id")],
            key=lambda x: (*(video_parts(str(x.get("id"))) or (-1, -1)), str(x.get("released") or "")),
        )

    @staticmethod
    def _series_imdb(item: dict[str, Any]) -> str:
        content_id = str(item.get("_id") or "")
        if re.fullmatch(r"tt\d+", content_id, flags=re.I):
            return content_id
        state = item.get("state") if isinstance(item.get("state"), dict) else {}
        for candidate in [str(state.get("video_id") or ""), watched_anchor(str(state.get("watched") or ""))]:
            imdb = candidate.split(":", 1)[0]
            if re.fullmatch(r"tt\d+", imdb, flags=re.I):
                return imdb
        return ""

    @staticmethod
    def _progress_values(state: dict[str, Any]) -> tuple[int, int] | None:
        try:
            position = int(state.get("timeOffset") or 0)
            duration = int(state.get("duration") or 0)
        except (TypeError, ValueError):
            return None
        return (position, duration) if position > 0 and duration > 0 else None


def default_state() -> dict[str, Any]:
    return {
        "lastWatched": None,
        "timeWatched": 0,
        "timeOffset": 0,
        "overallTimeWatched": 0,
        "timesWatched": 0,
        "flaggedWatched": 0,
        "duration": 0,
        "video_id": None,
        "watched": None,
        "noNotif": False,
    }


def new_item(item: WatchedItem | ProgressItem, now: str) -> dict[str, Any]:
    return {
        "_id": item.key.imdb,
        "name": item.title or item.key.imdb,
        "type": "movie" if item.key.kind == "movie" else "series",
        "poster": None,
        "posterShape": "poster",
        "removed": False,
        "temp": True,
        "_ctime": now,
        "_mtime": now,
        "state": default_state(),
        "behaviorHints": {},
    }


def video_parts(video_id: str) -> tuple[int, int] | None:
    parts = str(video_id or "").split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[-2]), int(parts[-1])
    except ValueError:
        return None


def find_video(videos: list[dict[str, Any]], season: int | None, episode: int | None) -> dict[str, Any] | None:
    for video in videos:
        if video_parts(str(video.get("id") or "")) == (season, episode):
            return video
    return None


def watched_anchor(serialized: str) -> str:
    try:
        return serialized.rsplit(":", 2)[0]
    except Exception:
        return ""


def decode_watched(serialized: Any, video_ids: list[str]) -> set[str]:
    if not serialized or not video_ids:
        return set()
    try:
        anchor, anchor_len_raw, encoded = str(serialized).rsplit(":", 2)
        anchor_len = int(anchor_len_raw)
        anchor_index = video_ids.index(anchor)
        packed = zlib.decompress(base64.b64decode(encoded))
    except Exception:
        return set()
    offset = (anchor_len - 1) - anchor_index
    result: set[str] = set()
    for index, video_id in enumerate(video_ids):
        old_index = index + offset
        if old_index < 0 or old_index >= anchor_len:
            continue
        byte_i, bit_i = divmod(old_index, 8)
        if byte_i < len(packed) and packed[byte_i] & (1 << bit_i):
            result.add(video_id)
    return result


def encode_watched(watched_ids: set[str], video_ids: list[str]) -> str | None:
    if not video_ids:
        return None
    values = bytearray((len(video_ids) + 7) // 8)
    last_index = 0
    for index, video_id in enumerate(video_ids):
        if video_id in watched_ids:
            byte_i, bit_i = divmod(index, 8)
            values[byte_i] |= 1 << bit_i
            last_index = index
    compressed = base64.b64encode(zlib.compress(bytes(values))).decode("ascii")
    return f"{video_ids[last_index]}:{last_index + 1}:{compressed}"


def compact_compare(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k != "_mtime"}
