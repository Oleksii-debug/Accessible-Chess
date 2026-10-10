"""Negative and positive tests for test-only real-corpus ZIP ingress."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch
import stat
import tempfile
import unittest
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

from tools.section38_bounded_zip_member import extract_member


class BoundedZipMemberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "real-publisher.zip"
        self.destination = self.root / "original.pgn"

    def write_zip(self, entries):
        with ZipFile(self.archive, "w", compression=ZIP_DEFLATED) as zip_file:
            for name, contents in entries:
                zip_file.writestr(name, contents)

    def assert_refused(self, label=""):
        with self.assertRaises((ValueError, OSError, BadZipFile)):
            extract_member(self.archive, "original.pgn", self.destination, max_bytes=128)
        self.assertFalse(self.destination.exists(), label)
        self.assertEqual(list(self.root.glob(".section38-*.partial")), [])

    def test_original_member_is_extracted_and_sha_is_a_real_byte_digest(self):
        original = b'[Event "Original"]\n1. e4 e5 1-0\n'
        self.write_zip([("license.txt", b"license"), ("original.pgn", original)])
        digest = extract_member(self.archive, "original.pgn", self.destination, max_bytes=128)
        self.assertEqual(digest, hashlib.sha256(original).hexdigest())
        self.assertEqual(self.destination.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "destination already exists"):
            extract_member(self.archive, "original.pgn", self.destination, max_bytes=128)
        self.assertEqual(self.destination.read_bytes(), original)

    def test_missing_and_duplicate_entries_refuse(self):
        self.write_zip([("other.pgn", b"data")])
        self.assert_refused("missing")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.write_zip([("original.pgn", b"a"), ("original.pgn", b"b")])
        self.assert_refused("duplicate")

    def test_unsafe_unrelated_traversal_refused(self):
        for bad in ("../private", "/absolute", "other\\evil", "folder/../private", "C:evil"):
            with self.subTest(path=bad):
                self.write_zip([("original.pgn", b"valid"), (bad, b"data")])
                # On Windows ZipInfo converts backslashes to forward slashes
                # when constructing a new member. Restore the exact hostile
                # raw archive name in both local and central headers before
                # testing the *reader*'s rejection of that original name.
                if "\\\\" in bad:
                    normalized = bad.replace("\\\\", "/").encode("utf-8")
                    original = bad.encode("utf-8")
                    raw_archive = self.archive.read_bytes()
                    self.assertIn(normalized, raw_archive)
                    self.archive.write_bytes(raw_archive.replace(normalized, original))
                self.assert_refused(bad)

    def test_refuses_budget_exhaustion_and_bad_args(self):
        self.write_zip([("original.pgn", b"A" * 129)])
        self.assert_refused("over budget")
        for budget in (0, -1, True, 129 * 1024 * 1024):
            with self.assertRaises(ValueError):
                extract_member(self.archive, "original.pgn", self.destination, max_bytes=budget)
        for name in ("../original.pgn", "sub/original.pgn", "..", "/original.pgn"):
            with self.assertRaises(ValueError):
                extract_member(self.archive, name, self.destination, max_bytes=128)

    def test_source_symlink_and_nonregular_member_refused(self):
        self.write_zip([("original.pgn", b"valid")])
        symlink_archive = self.root / "indirect.zip"
        symlink_archive.symlink_to(self.archive)
        with self.assertRaisesRegex(ValueError, "indirect"):
            extract_member(symlink_archive, "original.pgn", self.destination, max_bytes=128)
        self.assertFalse(self.destination.exists())
        link = ZipInfo("original.pgn")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(self.archive, "w", compression=ZIP_STORED) as z:
            z.writestr(link, "evil")
        self.assert_refused("ZIP symbolic link")

    def test_concurrent_owner_file_cannot_be_overwritten(self):
        self.write_zip([("original.pgn", b"downloaded-content")])
        original_link = __import__("os").link

        def competing_owner(source, destination):
            Path(destination).write_bytes(b"PRIVATE OWNER DATA")
            return original_link(source, destination)

        with patch("tools.section38_bounded_zip_member.os.link", side_effect=competing_owner):
            with self.assertRaises(FileExistsError):
                extract_member(self.archive, "original.pgn", self.destination, max_bytes=128)
        self.assertEqual(self.destination.read_bytes(), b"PRIVATE OWNER DATA")
        self.assertEqual(list(self.root.glob(".section38-*.partial")), [])

    def test_crc_failure_does_not_publish_partial_destination(self):
        with ZipFile(self.archive, "w", compression=ZIP_STORED) as z:
            z.writestr("original.pgn", b"original-byte-payload")
        data = self.archive.read_bytes()
        self.archive.write_bytes(data.replace(b"original-byte-payload", b"CORRUPTED-byte-payload"))
        self.assert_refused("CRC mismatch")


if __name__ == "__main__":
    unittest.main()
