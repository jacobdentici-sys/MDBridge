from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DATA_DIR = Path(os.environ.get("MDBRIDGE_DATA_DIR", "/data"))
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"


class Settings(BaseModel):
    mdblist_api_key: str = ""
    tmdb_token: str = ""
    nuvio_refresh_token: str = ""
    nuvio_profile_id: int = 1
    stremio_auth_key: str = ""
    addon_token: str = Field(default_factory=lambda: secrets.token_urlsafe(24))
    sync_interval_seconds: int = 900
    import_nuvio: bool = True
    import_stremio: bool = True
    push_nuvio: bool = True
    push_stremio: bool = True


def load_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env_interval = int(os.environ.get("MDBRIDGE_SYNC_INTERVAL", "900"))
    if not CONFIG_PATH.exists():
        settings = Settings(sync_interval_seconds=max(30, env_interval))
        save_settings(settings)
        return settings
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except Exception:
        data = {}
    settings = Settings.model_validate(data)
    settings.sync_interval_seconds = max(30, int(settings.sync_interval_seconds or env_interval))
    return settings


def save_settings(settings: Settings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(settings.model_dump(), indent=2))
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
