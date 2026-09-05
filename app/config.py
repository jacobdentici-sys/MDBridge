from __future__ import annotations

import json
import os
import secrets
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

DATA_DIR = Path(os.environ.get("MDBRIDGE_DATA_DIR", "/data"))
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"


class Settings(BaseModel):
    mdblist_api_key: str = ""
    tmdb_token: str = ""
    nuvio_refresh_token: str = ""
    nuvio_profile_id: int = Field(default=1, ge=1)
    stremio_auth_key: str = ""
    addon_token: str = Field(default_factory=lambda: secrets.token_urlsafe(24))
    sync_interval_seconds: int = Field(default=900, ge=30)
    import_nuvio: bool = True
    import_stremio: bool = True
    push_nuvio: bool = True
    push_stremio: bool = True


def load_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        env_interval = max(30, int(os.environ.get("MDBRIDGE_SYNC_INTERVAL", "900")))
    except ValueError as exc:
        raise RuntimeError("MDBRIDGE_SYNC_INTERVAL must be an integer") from exc
    if not CONFIG_PATH.exists():
        settings = Settings(sync_interval_seconds=env_interval)
        save_settings(settings)
        return settings
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return Settings.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(
            f"Could not load {CONFIG_PATH}; restore a backup or correct the file"
        ) from exc


def save_settings(settings: Settings) -> None:
    _write_json_atomic(CONFIG_PATH, settings.model_dump())


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    _write_json_atomic(STATE_PATH, state, sort_keys=True)


def _write_json_atomic(path: Path, value: Any, *, sort_keys: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=sort_keys)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temp_path.chmod(0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
