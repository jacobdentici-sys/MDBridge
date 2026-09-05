from __future__ import annotations

from typing import Any

import httpx

from .models import MediaKey

BASE = "https://api.themoviedb.org/3"


class TMDBClient:
    def __init__(self, token: str):
        self.token = token
        self._find_cache: dict[tuple[str, str], int | None] = {}
        self._duration_cache: dict[str, int | None] = {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "accept": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{BASE}{path}", headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def validate(self) -> bool:
        if not self.token:
            return False
        try:
            await self._get("/configuration")
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def find_imdb(self, imdb: str, kind: str) -> int | None:
        cache_key = (imdb, kind)
        if cache_key in self._find_cache:
            return self._find_cache[cache_key]
        data = await self._get(f"/find/{imdb}", {"external_source": "imdb_id"})
        key = "movie_results" if kind == "movie" else "tv_results"
        rows = data.get(key) or []
        value = int(rows[0]["id"]) if rows else None
        self._find_cache[cache_key] = value
        return value

    async def imdb_from_tmdb(self, tmdb_id: int, kind: str) -> str | None:
        path = f"/movie/{tmdb_id}/external_ids" if kind == "movie" else f"/tv/{tmdb_id}/external_ids"
        data = await self._get(path)
        value = str(data.get("imdb_id") or "")
        return value if value.startswith("tt") else None

    async def duration_ms(self, key: MediaKey, tmdb_id: int | None = None) -> int | None:
        if key.stable_id in self._duration_cache:
            return self._duration_cache[key.stable_id]
        runtime: int | None = None
        if key.kind == "movie":
            movie_id = tmdb_id or await self.find_imdb(key.imdb, "movie")
            if movie_id:
                data = await self._get(f"/movie/{movie_id}")
                runtime = _int(data.get("runtime"))
        else:
            show_id = await self.find_imdb(key.imdb, "series")
            if show_id:
                data = await self._get(f"/tv/{show_id}/season/{key.season}/episode/{key.episode}")
                runtime = _int(data.get("runtime"))
        value = runtime * 60_000 if runtime and runtime > 0 else None
        self._duration_cache[key.stable_id] = value
        return value


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
