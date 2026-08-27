from __future__ import annotations

import os
from pathlib import Path
import unittest
import zipfile

from acs.release_preflight import ReleasePreflightError, inspect_release_package
from tests.test_release_preflight import ReleasePreflightTests


_MIB = 1024 * 1024


class D04StockfishSourceZipBoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._fixture = ReleasePreflightTests(methodName="test_unicode_space_tree_and_inventory_are_deterministic")
        self.addCleanup(self._fixture.doCleanups)

    def make_package(self) -> Path:
        return self._fixture.make_package()

    def rewrite_checksums(self, root: Path) -> None:
        self._fixture.rewrite_checksums(root)

    @staticmethod
    def source_zip(root: Path) -> Path:
        return root / "THIRD_PARTY_NOTICES" / "Stockfish-18-source.zip"

    @staticmethod
    def add_license(archive: zipfile.ZipFile) -> None:
        archive.writestr(
            "Stockfish-sf_18/Copying.txt",
            "GNU GENERAL PUBLIC LICENSE\nVersion 3\n",
        )

    def assert_rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn(fragment, str(caught.exception))

    def test_source_zip_entry_count_is_bounded_before_crc_walk(self) -> None:
        root = self.make_package()
        with zipfile.ZipFile(self.source_zip(root), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self.add_license(archive)
            for index in range(4097):
                archive.writestr(f"Stockfish-sf_18/src/unit_{index:04d}.cpp", "")
        self.rewrite_checksums(root)
        self.assert_rejected(root, "too many entries")

    def test_source_zip_compressed_file_size_is_bounded(self) -> None:
        root = self.make_package()
        with zipfile.ZipFile(self.source_zip(root), "w", compression=zipfile.ZIP_STORED) as archive:
            self.add_license(archive)
            archive.writestr("Stockfish-sf_18/src/blob.bin", os.urandom(9 * _MIB))
        self.rewrite_checksums(root)
        self.assert_rejected(root, "archive is too large")

    def test_source_zip_single_uncompressed_member_is_bounded_before_testzip(self) -> None:
        root = self.make_package()
        with zipfile.ZipFile(self.source_zip(root), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self.add_license(archive)
            archive.writestr("Stockfish-sf_18/src/oversized.cpp", b"A" * (17 * _MIB))
        self.rewrite_checksums(root)
        self.assert_rejected(root, "member is too large")

    def test_source_zip_total_uncompressed_bytes_are_bounded_before_testzip(self) -> None:
        root = self.make_package()
        chunk = b"B" * (13 * _MIB)
        with zipfile.ZipFile(self.source_zip(root), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self.add_license(archive)
            for index in range(5):
                archive.writestr(f"Stockfish-sf_18/src/large_{index}.cpp", chunk)
        self.rewrite_checksums(root)
        self.assert_rejected(root, "uncompressed payload is too large")


if __name__ == "__main__":
    unittest.main()
