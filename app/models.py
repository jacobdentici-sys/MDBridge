from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        # Millisecond epochs are common in Nuvio.
        seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str) and value:
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(0, tz=UTC)


@dataclass(frozen=True, slots=True)
class MediaKey:
    kind: Literal["movie", "episode"]
    imdb: str
    season: int | None = None
    episode: int | None = None

    def __post_init__(self) -> None:
        if not self.imdb.startswith("tt"):
            raise ValueError(f"IMDb id required, got {self.imdb!r}")
        if self.kind == "episode" and (self.season is None or self.episode is None):
            raise ValueError("Episode keys require season and episode")

    @property
    def stable_id(self) -> str:
        if self.kind == "movie":
            return f"movie:{self.imdb}"
        return f"episode:{self.imdb}:S{self.season:02d}E{self.episode:02d}"


@dataclass(slots=True)
class WatchedItem:
    key: MediaKey
    watched_at: datetime
    title: str = ""
    source: str = ""


@dataclass(slots=True)
class ProgressItem:
    key: MediaKey
    percent: float
    updated_at: datetime
    duration_ms: int | None = None
    position_ms: int | None = None
    title: str = ""
    source: str = ""
    tmdb_id: int | None = None

    def normalized(self) -> ProgressItem:
        self.percent = max(0.0, min(100.0, float(self.percent)))
        if self.duration_ms and not self.position_ms:
            self.position_ms = int(self.duration_ms * self.percent / 100.0)
        if self.position_ms and self.duration_ms and self.duration_ms > 0:
            self.percent = max(0.0, min(100.0, 100.0 * self.position_ms / self.duration_ms))
        return self
