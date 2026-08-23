from __future__ import annotations

from collections import defaultdict
from typing import Any

import httpx

from .models import MediaKey, ProgressItem, WatchedItem, parse_time


BASE = "https://api.mdblist.com"


class MDBListClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def _request(self, method: str, path: str, *, params=None, json=None) -> Any:
        query = dict(params or {})
        query["apikey"] = self.api_key
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, f"{BASE}{path}", params=query, json=json)
            _raise_for_status(method, path, response)
            return response.json() if response.content else {}

    async def validate(self) -> bool:
        if not self.api_key:
            return False
        try:
            await self._request("GET", "/sync/last_activities")
            return True
        except Exception:
            return False

    async def playback(self) -> dict[str, ProgressItem]:
        rows = await self._request("GET", "/sync/playback")
        result: dict[str, ProgressItem] = {}
        if not isinstance(rows, list):
            return result
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type") or "")
            progress = float(row.get("progress") or 0)
            paused_at = parse_time(row.get("paused_at"))
            if kind == "movie":
                movie = row.get("movie") or {}
                ids = movie.get("ids") or {}
                imdb = str(ids.get("imdbid") or ids.get("imdb") or "")
                if not imdb.startswith("tt"):
                    continue
                key = MediaKey("movie", imdb)
                item = ProgressItem(
                    key=key,
                    percent=progress,
                    updated_at=paused_at,
                    title=str(movie.get("title") or ""),
                    source="mdblist",
                    tmdb_id=_int(ids.get("tmdbid") or ids.get("tmdb")),
                )
            elif kind in {"episode", "show"}:
                episode = row.get("episode") or {}
                show = row.get("show") or {}
                show_ids = show.get("ids") or {}
                imdb = str(show_ids.get("imdbid") or show_ids.get("imdb") or "")
                season = _int(episode.get("season"))
                number = _int(episode.get("number"))
                if not imdb.startswith("tt") or season is None or number is None:
                    continue
                key = MediaKey("episode", imdb, season, number)
                item = ProgressItem(
                    key=key,
                    percent=progress,
                    updated_at=paused_at,
                    title=str(episode.get("title") or show.get("title") or ""),
                    source="mdblist",
                    tmdb_id=_int((episode.get("ids") or {}).get("tmdbid") or (episode.get("ids") or {}).get("tmdb")),
                )
            else:
                continue
            result[key.stable_id] = item.normalized()
        return result

    async def watched(self) -> dict[str, WatchedItem]:
        result: dict[str, WatchedItem] = {}
        offset = 0
        limit = 1000
        while True:
            payload = await self._request("GET", "/sync/watched", params={"offset": offset, "limit": limit})
            if not isinstance(payload, dict):
                break
            for entry in payload.get("movies", []) or []:
                movie = entry.get("movie") or entry
                ids = movie.get("ids") or {}
                imdb = str(ids.get("imdb") or "")
                if imdb.startswith("tt"):
                    key = MediaKey("movie", imdb)
                    result[key.stable_id] = WatchedItem(
                        key=key,
                        watched_at=parse_time(entry.get("last_watched_at") or entry.get("watched_at")),
                        title=str(movie.get("title") or ""),
                        source="mdblist",
                    )
            for entry in payload.get("episodes", []) or []:
                ep = entry.get("episode") or entry
                show = ep.get("show") or entry.get("show") or {}
                ids = show.get("ids") or {}
                imdb = str(ids.get("imdb") or "")
                season = _int(ep.get("season"))
                number = _int(ep.get("number"))
                if imdb.startswith("tt") and season is not None and number is not None:
                    key = MediaKey("episode", imdb, season, number)
                    result[key.stable_id] = WatchedItem(
                        key=key,
                        watched_at=parse_time(entry.get("last_watched_at") or entry.get("watched_at")),
                        title=str(ep.get("name") or show.get("title") or ""),
                        source="mdblist",
                    )
            pagination = payload.get("pagination") or {}
            if not pagination.get("has_more"):
                break
            offset += limit
        return result

    async def add_watched(self, items: list[WatchedItem]) -> None:
        if not items:
            return
        movies: list[dict[str, Any]] = []
        shows: dict[str, dict[str, Any]] = {}
        for item in items:
            watched_at = item.watched_at.isoformat().replace("+00:00", "Z")
            if item.key.kind == "movie":
                movies.append({"ids": {"imdb": item.key.imdb}, "watched_at": watched_at})
            else:
                show = shows.setdefault(item.key.imdb, {"ids": {"imdb": item.key.imdb}, "seasons": {}})
                seasons = show["seasons"]
                season = seasons.setdefault(item.key.season, {"number": item.key.season, "episodes": []})
                season["episodes"].append({"number": item.key.episode, "watched_at": watched_at})
        show_payload = []
        for show in shows.values():
            show_payload.append({"ids": show["ids"], "seasons": list(show["seasons"].values())})
        # Keep well below MDBList's 200 top-level item limit.
        for start in range(0, max(len(movies), len(show_payload), 1), 100):
            payload = {"movies": movies[start:start+100], "shows": show_payload[start:start+100]}
            if payload["movies"] or payload["shows"]:
                await self._request("POST", "/sync/watched", json=payload)

    async def set_progress(self, item: ProgressItem) -> None:
        body = _scrobble_body(item)
        # Start then pause guarantees a retained resume session even if there was no existing active session.
        await self._request("POST", "/scrobble/start", json=body)
        await self._request("POST", "/scrobble/pause", json=body)

    async def clear_progress(self, key: MediaKey) -> None:
        body = _key_body(key)
        try:
            await self._request("POST", "/scrobble/clear", json=body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise


def _key_body(key: MediaKey) -> dict[str, Any]:
    if key.kind == "movie":
        return {"movie": {"ids": {"imdb": key.imdb}}}
    return {
        "show": {
            "ids": {"imdb": key.imdb},
            "season": {"number": key.season, "episode": {"number": key.episode}},
        }
    }


def _scrobble_body(item: ProgressItem) -> dict[str, Any]:
    body = _key_body(item.key)
    body["progress"] = round(max(0.0, min(100.0, item.percent)), 1)
    body["app_version"] = "MDBridge/0.1.1"
    return body


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raise_for_status(method: str, path: str, response: httpx.Response) -> None:
    """Raise an error that never includes the API key from the request URL."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"MDBList {method.upper()} {path} failed with HTTP {exc.response.status_code}"
        ) from None
