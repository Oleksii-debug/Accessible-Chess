from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.version2_package_preflight import (
    PackageLimits,
    Version2PackagePreflightError,
    _validate_zip_entries,
    validate_version2_package_tree,
)
from tests.test_version2_package_preflight import _SHA, _make_tree, _write_checksums


_SOURCE_ARCHIVE = Path("THIRD_PARTY_NOTICES") / "Stockfish-18-source.zip"


def _rewrite_source_archive(
    root: Path,
    entries: tuple[tuple[str, bytes | str], ...],
) -> Path:
    source_archive = root / _SOURCE_ARCHIVE
    with zipfile.ZipFile(source_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    _write_checksums(root)
    return source_archive


def _validate_tree(root: Path, *, limits: PackageLimits = PackageLimits()) -> None:
    validate_version2_package_tree(
        root,
        expected_integration_sha=_SHA,
        limits=limits,
    )


class StockfishSourceArchivePreflightTests(unittest.TestCase):
    def test_legitimate_raw_corresponding_source_remains_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)

            _validate_tree(root)

    def test_inner_source_archive_rejects_windows_casefold_collision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            _rewrite_source_archive(
                root,
                (
                    ("Stockfish/src/main.cpp", b"int main() { return 0; }\n"),
                    ("stockfish/SRC/MAIN.cpp", b"duplicate\n"),
                ),
            )

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "collide under Windows case-folding",
            ):
                _validate_tree(root)

    def test_inner_source_archive_requires_real_file_under_src(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            _rewrite_source_archive(
                root,
                (
                    ("Stockfish/src/", b""),
                    ("Stockfish/Copying.txt", b"GNU GPL v3\n"),
                ),
            )

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "does not contain source files",
            ):
                _validate_tree(root)

    def test_inner_source_archive_honors_archive_and_member_size_limits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "source archive exceeds archive byte limit",
            ):
                _validate_tree(root, limits=PackageLimits(max_archive_bytes=1))

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "member exceeds uncompressed size limit",
            ):
                _validate_tree(root, limits=PackageLimits(max_member_bytes=8))

    def test_shared_zip_safety_rejects_inner_member_count_and_total_size(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "source.zip"
            with zipfile.ZipFile(
                archive_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as writer:
                writer.writestr("Stockfish/src/a.cpp", b"aaaaa")
                writer.writestr("Stockfish/src/b.cpp", b"bbbbb")
                writer.writestr("Stockfish/Copying.txt", b"GPL")

            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "member-count limit",
                ):
                    _validate_zip_entries(
                        archive,
                        PackageLimits(max_files=1),
                        enforce_package_file_policy=False,
                    )

            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "total uncompressed byte limit",
                ):
                    _validate_zip_entries(
                        archive,
                        PackageLimits(max_bytes=8),
                        enforce_package_file_policy=False,
                    )

    def test_shared_zip_safety_rejects_inner_unsafe_path_and_compression_bomb(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            unsafe_path = Path(td) / "unsafe.zip"
            with zipfile.ZipFile(unsafe_path, "w", compression=zipfile.ZIP_DEFLATED) as writer:
                writer.writestr("../src/main.cpp", b"source\n")
            with zipfile.ZipFile(unsafe_path) as archive:
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "unsafe",
                ):
                    _validate_zip_entries(
                        archive,
                        PackageLimits(),
                        enforce_package_file_policy=False,
                    )

            compressed_path = Path(td) / "compressed.zip"
            with zipfile.ZipFile(
                compressed_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as writer:
                writer.writestr("Stockfish/src/zeros.cpp", b"0" * 4096)
            with zipfile.ZipFile(compressed_path) as archive:
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "compression-ratio limit",
                ):
                    _validate_zip_entries(
                        archive,
                        PackageLimits(max_compression_ratio=2),
                        enforce_package_file_policy=False,
                    )


if __name__ == "__main__":
    unittest.main()
