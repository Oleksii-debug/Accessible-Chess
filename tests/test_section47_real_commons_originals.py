"""Adversarial offline checks for real Commons source integrity and TEST_BUILD receipts."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools" / "section47_download_commons_corpus.py"
SPEC = importlib.util.spec_from_file_location("section47_original_corpus", MODULE)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def source(data: bytes) -> tuple[dict, dict]:
    sha = hashlib.sha1(data).hexdigest()
    item = {
        "video_id": "fixture-chess-test",
        "filename": "Fixture_chess_test.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Fixture_chess_test.webm",
        "author": "Fixture Author",
        "license_id": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "duration_seconds": 2.0,
    }
    metadata = {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/12/Fixture_chess_test.webm",
        "sha1": sha, "size": len(data),
        "mime": "video/webm", "timestamp": "fixture-revision",
    }
    return item, metadata


class RealOriginalDownloadTest(unittest.TestCase):
    def test_catalog_is_real_existing_owner_source(self):
        catalog = tool.json.loads(tool.SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(catalog["schema_version"], 1)
        self.assertGreaterEqual(len(catalog["videos"]), 4)
        for entry in catalog["videos"]:
            self.assertEqual(entry["expected_sha256"], None)
            self.assertIn(entry["license_id"], {"CC0-1.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0"})
            self.assertTrue(entry["source_page"].startswith("https://commons.wikimedia.org/wiki/File:"))
        self.assertEqual(
            tool.PINNED_ORIGINAL_SHA1["byrne-fischer-game-century"],
            "022b2c55b284c9586c5bee695d82af3a582b2adc",
        )

    def test_blocks_youtube_and_cross_origin_redirect(self):
        for url in ("https://www.youtube.com/watch?v=M7lc1UVf-VE",
                    "http://upload.wikimedia.org/a",
                    "https://user:secret@upload.wikimedia.org/a",
                    "https://upload.wikimedia.org:8443/a"):
            with self.subTest(url=url):
                with self.assertRaises(tool.OriginalError):
                    tool.open_url(url)
        handler = tool.CommonsOnlyRedirect()
        req = tool.urllib.request.Request("https://commons.wikimedia.org/a")
        with self.assertRaises(tool.OriginalError):
            handler.redirect_request(req, None, 302, "Redirect", {},
                                     "https://outside.example/not-media.webm")

    def test_original_bytes_sha1_sha256_and_temp_cleanup(self):
        blob = bytes.fromhex("1a45dfa3") + b"actual-byte-stream-fixture"
        entry, meta = source(blob)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch.object(tool, "api_identity", return_value=meta),
                patch.object(tool, "open_url", side_effect=lambda _: io.BytesIO(blob)),
                patch.object(tool.shutil, "which", return_value=None),
            ):
                receipt = tool.download_one(entry, root, False)
            self.assertEqual(receipt["sha1"], meta["sha1"])
            self.assertEqual(receipt["sha256"], hashlib.sha256(blob).hexdigest())
            self.assertEqual(receipt["filename"], entry["filename"])
            self.assertEqual(receipt["license"], entry["license_id"])
            self.assertEqual(receipt["creator"], entry["author"])
            self.assertTrue(receipt["original_bytes_verified"])
            self.assertFalse(receipt["decoded"])
            self.assertFalse(receipt["chess_position_qualified"])
            self.assertEqual((root / entry["filename"]).read_bytes(), blob)
            self.assertEqual(len(list(root.iterdir())), 1)
            with self.assertRaises(tool.OriginalError):
                tool.download_one(entry, root, False)

    def test_remote_digest_mismatch_never_publishes_partial_video(self):
        blob = bytes.fromhex("1a45dfa3") + b"tamper"
        entry, meta = source(blob)
        meta["sha1"] = "0" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch.object(tool, "api_identity", return_value=meta),
                patch.object(tool, "open_url", side_effect=lambda _: io.BytesIO(blob)),
            ):
                with self.assertRaises(tool.OriginalError):
                    tool.download_one(entry, root, False)
            self.assertEqual(list(root.iterdir()), [])

    def test_bad_source_title_and_path_traversal_rejected(self):
        blob = bytes.fromhex("1a45dfa3") + b"fixture"
        entry, meta = source(blob)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for bad in ("../evil.webm", r"..\evil.webm", "fake.mp4", "/absolute.webm"):
                e = {**entry, "filename": bad}
                with self.subTest(bad=bad):
                    with self.assertRaises(tool.OriginalError):
                        tool.download_one(e, root, False)
            with self.assertRaises(tool.OriginalError):
                tool.download_one(
                    {**entry, "source_page": "https://fake.example/wiki/File:Fixture_chess_test.webm"},
                    root, False,
                )

    def test_changed_original_revision_fails_before_fetch(self):
        blob = bytes.fromhex("1a45dfa3") + b"fixture"
        entry, meta = source(blob)
        entry["video_id"] = "byrne-fischer-game-century"
        meta["sha1"] = "0" * 40
        with tempfile.TemporaryDirectory() as td:
            with patch.object(tool, "api_identity", return_value=meta), patch.object(
                tool, "open_url", side_effect=AssertionError("must not fetch tampered revision")
            ):
                with self.assertRaises(tool.OriginalError):
                    tool.download_one(entry, Path(td), False)


if __name__ == "__main__":
    unittest.main()
