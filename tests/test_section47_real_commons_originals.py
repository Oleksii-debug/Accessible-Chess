"""Offline adversarial tests for the lawful, source-bound original video pipeline."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "tools" / "section47_download_commons_corpus.py"
SPEC = importlib.util.spec_from_file_location("section47_originals", MODULE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def entry(sha1):
    return {
        "file": "Chess test.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Chess_test.webm",
        "creator": "Test", "license": "CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "expected_sha1": sha1,
        "expected_timecodes_seconds": [0, 1],
    }


class OriginalFixtureQualificationTest(unittest.TestCase):
    def test_rejects_non_commons_download_and_unsafe_redirect(self):
        for address in (
            "https://www.youtube.com/watch?v=M7lc1UVf-VE",
            "http://commons.wikimedia.org/",
            "https://user:password@upload.wikimedia.org/a",
            "https://upload.wikimedia.org:444/a",
        ):
            with self.subTest(address=address):
                with self.assertRaises(module.OriginalError):
                    module.open_url(address)
        handler = module.CommonsOnlyRedirect()
        request = module.urllib.request.Request("https://commons.wikimedia.org/a")
        with self.assertRaises(module.OriginalError):
            handler.redirect_request(request, None, 302, "redirect", {}, "https://evil.example/b")

    def test_success_reads_real_bytes_and_never_claims_position_or_windows_acceptance(self):
        data = b"\x1a\x45\xdf\xa3Chess only test fixture"
        sha1, sha256 = hashlib.sha1(data).hexdigest(), hashlib.sha256(data).hexdigest()
        info = {
            "url": "https://upload.wikimedia.org/test.webm",
            "sha1": sha1,
            "size": len(data), "mime": "video/webm", "timestamp": "test-revision",
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(module, "api_identity", return_value=info), \
                 mock.patch.object(module, "open_url", side_effect=lambda _url: io.BytesIO(data)), \
                 mock.patch.object(module.shutil, "which", return_value=None):
                receipt = module.download_one(entry(sha1), Path(directory), False)
                self.assertEqual(receipt["sha256"], sha256)
                self.assertEqual(receipt["sha1"], sha1)
                self.assertTrue(receipt["original_bytes_verified"])
                self.assertFalse(receipt["decoded"])
                self.assertFalse(receipt["chess_position_qualified"])
                self.assertEqual((Path(directory) / "Chess test.webm").read_bytes(), data)
                with self.assertRaises(module.OriginalError):
                    module.download_one(entry(sha1), Path(directory), False)

    def test_source_digest_mismatch_fails_closed_without_partial_publication(self):
        data = b"\x1a\x45\xdf\xa3tamper"
        declared = "0" * 40
        info = {
            "url": "https://upload.wikimedia.org/test.webm", "sha1": declared,
            "size": len(data), "mime": "video/webm",
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(module, "api_identity", return_value=info), \
                 mock.patch.object(module, "open_url", side_effect=lambda _url: io.BytesIO(data)):
                with self.assertRaises(module.OriginalError):
                    module.download_one(entry(declared), Path(directory), False)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_unexpected_original_revision_without_download(self):
        entry_ = entry("1" * 40)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(module, "api_identity", return_value={"sha1": "2" * 40}):
                with self.assertRaises(module.OriginalError):
                    module.download_one(entry_, Path(directory), False)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_path_traversal_without_external_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../../hello.webm", r"..\hello.webm", "bad.mp4", "bad.exe"):
                with self.subTest(name=name):
                    item = entry(None); item["file"] = name
                    with self.assertRaises(module.OriginalError):
                        module.download_one(item, Path(directory), False)

    def test_catalog_requires_attribution_and_no_fake_original_sha256(self):
        catalog = module.json.loads(module.SOURCE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(catalog["originals"]), 3)
        for source in catalog["originals"]:
            self.assertTrue(source["page"].startswith("https://commons.wikimedia.org/wiki/File:"))
            self.assertTrue(source["creator"])
            self.assertTrue(source["license_url"].startswith("https://"))
            self.assertIsNone(source["expected_sha256"])
            self.assertFalse(source["download_verified"])
        for source in catalog["youtube"]:
            self.assertFalse(source["download_allowed"])
            self.assertEqual(source["embeddable"], "UNVERIFIED_LIVE")


if __name__ == "__main__":
    unittest.main()
