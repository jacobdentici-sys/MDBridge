import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from app import config as config_module
from app.config import Settings
from app.main import SettingsBody, public_error, update_settings
from app.mdblist import MDBListClient, MDBListHTTPError, _raise_for_status
from app.models import MediaKey, ProgressItem
from app.stremio import decode_watched, encode_watched, video_parts
from app.sync_engine import is_remote_newer, progress_needs_push
from app.ui import render_home


class CoreTests(unittest.TestCase):
    def test_media_key(self):
        self.assertEqual(MediaKey("movie", "tt1234567").stable_id, "movie:tt1234567")
        self.assertEqual(MediaKey("episode", "tt1234567", 2, 3).stable_id, "episode:tt1234567:S02E03")

    def test_watched_bitfield_roundtrip(self):
        ids = [f"tt1234567:1:{i}" for i in range(1, 11)]
        selected = {ids[0], ids[4], ids[9]}
        encoded = encode_watched(selected, ids)
        self.assertEqual(decode_watched(encoded, ids), selected)

    def test_video_parts(self):
        self.assertEqual(video_parts("tt1234567:4:9"), (4, 9))
        self.assertIsNone(video_parts("tt1234567"))

    def test_progress_normalization(self):
        item = ProgressItem(
            key=MediaKey("movie", "tt1234567"),
            percent=25,
            updated_at=datetime.now(UTC),
            duration_ms=400_000,
        ).normalized()
        self.assertEqual(item.position_ms, 100_000)

    def test_newer_progress(self):
        key = MediaKey("movie", "tt1234567")
        old = ProgressItem(key, 20, datetime(2026, 1, 1, tzinfo=UTC))
        new = ProgressItem(key, 30, datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
        self.assertTrue(is_remote_newer(new, old))

    def test_mdblist_errors_redact_api_key(self):
        request = httpx.Request("GET", "https://api.mdblist.com/sync/watched?apikey=do-not-log")
        response = httpx.Response(429, request=request)
        with self.assertRaises(RuntimeError) as raised:
            _raise_for_status("GET", "/sync/watched", response)
        self.assertIn("HTTP 429", str(raised.exception))
        self.assertNotIn("do-not-log", str(raised.exception))

    def test_public_http_error_does_not_include_request_url(self):
        request = httpx.Request("GET", "https://example.test/?token=do-not-log")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("unsafe", request=request, response=response)
        self.assertEqual(public_error(error), "Provider request failed with HTTP 503")

    def test_progress_push_skips_equivalent_remote_value(self):
        key = MediaKey("movie", "tt1234567")
        now = datetime.now(UTC)
        canonical = ProgressItem(key, 25.0, now)
        self.assertFalse(progress_needs_push(canonical, ProgressItem(key, 25.2, now)))
        self.assertTrue(progress_needs_push(canonical, ProgressItem(key, 26.0, now)))
        self.assertTrue(progress_needs_push(canonical, None))

    def test_example_interval_matches_quota_friendly_default(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("MDBRIDGE_SYNC_INTERVAL=900", (root / ".env.example").read_text())

    def test_settings_roundtrip_uses_no_leftover_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            config_path = data_dir / "config.json"
            state_path = data_dir / "state.json"
            with (
                patch.object(config_module, "DATA_DIR", data_dir),
                patch.object(config_module, "CONFIG_PATH", config_path),
                patch.object(config_module, "STATE_PATH", state_path),
            ):
                config_module.save_settings(Settings(sync_interval_seconds=900))
                loaded = config_module.load_settings()
                self.assertEqual(loaded.sync_interval_seconds, 900)
                self.assertEqual(list(data_dir.glob(".config.json.*")), [])

    def test_setup_page_contains_safe_interval_and_disconnect_controls(self):
        html = render_home(
            mdblist=True,
            tmdb=True,
            nuvio=True,
            stremio=True,
            sync_interval_seconds=900,
            addon_url="http://localhost/private/manifest.json",
        )
        self.assertIn('id="interval" type="number" min="30" value="900"', html)
        self.assertIn("disconnectNuvio()", html)
        self.assertIn("disconnectStremio()", html)
        self.assertNotIn("slink.innerHTML", html)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_progress_ignores_missing_session(self):
        client = MDBListClient("secret")
        with patch.object(
            client,
            "_request",
            new=AsyncMock(side_effect=MDBListHTTPError("POST", "/scrobble/clear", 404)),
        ):
            await client.clear_progress(MediaKey("movie", "tt1234567"))

    async def test_clear_progress_raises_other_failures(self):
        client = MDBListClient("secret")
        with patch.object(
            client,
            "_request",
            new=AsyncMock(side_effect=MDBListHTTPError("POST", "/scrobble/clear", 500)),
        ), self.assertRaises(MDBListHTTPError):
            await client.clear_progress(MediaKey("movie", "tt1234567"))

    async def test_invalid_mdblist_key_is_not_saved(self):
        current = Settings(mdblist_api_key="known-good")
        with (
            patch("app.main.load_settings", return_value=current),
            patch("app.main.save_settings") as save,
            patch("app.main.MDBListClient.validate", new=AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException):
                await update_settings(SettingsBody(mdblist_api_key="invalid"))
            save.assert_not_called()
            self.assertEqual(current.mdblist_api_key, "known-good")


if __name__ == "__main__":
    unittest.main()
