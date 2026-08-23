import unittest
from datetime import datetime, timezone

import httpx

from app.mdblist import _raise_for_status
from app.models import MediaKey, ProgressItem
from app.stremio import decode_watched, encode_watched, video_parts
from app.sync_engine import is_remote_newer


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
            updated_at=datetime.now(timezone.utc),
            duration_ms=400_000,
        ).normalized()
        self.assertEqual(item.position_ms, 100_000)

    def test_newer_progress(self):
        key = MediaKey("movie", "tt1234567")
        old = ProgressItem(key, 20, datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = ProgressItem(key, 30, datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc))
        self.assertTrue(is_remote_newer(new, old))

    def test_mdblist_errors_redact_api_key(self):
        request = httpx.Request("GET", "https://api.mdblist.com/sync/watched?apikey=do-not-log")
        response = httpx.Response(429, request=request)
        with self.assertRaises(RuntimeError) as raised:
            _raise_for_status("GET", "/sync/watched", response)
        self.assertIn("HTTP 429", str(raised.exception))
        self.assertNotIn("do-not-log", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
