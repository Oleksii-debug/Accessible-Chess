from __future__ import annotations

from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from acs.version2_package_preflight import (
    PackageLimits,
    Version2PackagePreflightError,
    _validate_stockfish_source_archive,
)


def _limits(**overrides: int) -> PackageLimits:
    values = {
        "max_files": 100,
        "max_bytes": 1024 * 1024,
        "max_archive_bytes": 1024 * 1024,
        "max_member_bytes": 1024 * 1024,
        "max_compression_ratio": 200,
        "max_text_scan_bytes": 1024,
    }
    values.update(overrides)
    return PackageLimits(**values)


def _write_archive(path: Path, entries: tuple[tuple[str, bytes], ...]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)


class StockfishSourceArchivePreflightTests(unittest.TestCase):
    def test_valid_bounded_source_archive_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (
                    ("Stockfish-sf_18/src/main.cpp", b"// source fixture\n"),
                    ("Stockfish-sf_18/Copying.txt", b"GNU GPL v3\n"),
                ),
            )
            _validate_stockfish_source_archive(archive_path, _limits())

    def test_archive_file_size_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (("Stockfish-sf_18/src/main.cpp", b"// source fixture\n"),),
            )
            archive_size = archive_path.stat().st_size
            self.assertGreater(archive_size, 1)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "archive byte limit"
            ):
                _validate_stockfish_source_archive(
                    archive_path,
                    _limits(max_archive_bytes=archive_size - 1),
                )

    def test_unsafe_and_reserved_paths_fail_closed(self):
        cases = (
            ("../escape.cpp", "unsafe"),
            ("Stockfish/src/../escape.cpp", "unsafe"),
            ("Stockfish/src/COM1.cpp", "reserved Windows name"),
        )
        for name, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "Stockfish-18-source.zip"
                _write_archive(
                    archive_path,
                    (
                        (name, b"malicious\n"),
                        ("Stockfish/src/valid.cpp", b"valid\n"),
                    ),
                )
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_stockfish_source_archive(archive_path, _limits())

    def test_casefold_collision_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (
                    ("Stockfish/src/Main.cpp", b"one\n"),
                    ("stockfish/src/main.cpp", b"two\n"),
                ),
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "collide under Windows case-folding"
            ):
                _validate_stockfish_source_archive(archive_path, _limits())

    def test_symlink_and_special_file_fail_closed(self):
        cases = (
            (stat.S_IFLNK | 0o777, "symbolic links"),
            (stat.S_IFIFO | 0o600, "special files"),
        )
        for mode, expected in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "Stockfish-18-source.zip"
                with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("Stockfish/src/valid.cpp", b"valid\n")
                    info = zipfile.ZipInfo("Stockfish/unsafe-entry")
                    info.create_system = 3
                    info.external_attr = mode << 16
                    archive.writestr(info, b"target")
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_stockfish_source_archive(archive_path, _limits())

    def test_file_and_member_count_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (
                    ("Stockfish/src/a.cpp", b"a"),
                    ("Stockfish/src/b.cpp", b"b"),
                ),
            )
            with self.assertRaisesRegex(Version2PackagePreflightError, "file-count"):
                _validate_stockfish_source_archive(
                    archive_path, _limits(max_files=1)
                )

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("one/", b"")
                archive.writestr("two/", b"")
                archive.writestr("three/", b"")
            with self.assertRaisesRegex(Version2PackagePreflightError, "member-count"):
                _validate_stockfish_source_archive(
                    archive_path, _limits(max_files=1)
                )

    def test_member_total_and_compression_ratio_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (("Stockfish/src/main.cpp", b"12345"),),
            )
            with self.assertRaisesRegex(Version2PackagePreflightError, "member exceeds"):
                _validate_stockfish_source_archive(
                    archive_path, _limits(max_member_bytes=4)
                )

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (
                    ("Stockfish/src/a.cpp", b"12345"),
                    ("Stockfish/src/b.cpp", b"67890"),
                ),
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "total uncompressed byte limit"
            ):
                _validate_stockfish_source_archive(
                    archive_path,
                    _limits(max_bytes=8, max_member_bytes=8),
                )

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (("Stockfish/src/main.cpp", b"A" * 4096),),
            )
            with self.assertRaisesRegex(Version2PackagePreflightError, "compression-ratio"):
                _validate_stockfish_source_archive(
                    archive_path, _limits(max_compression_ratio=2)
                )

    def test_src_directory_or_empty_src_file_is_not_corresponding_source(self):
        cases = (
            (
                ("Stockfish/src/", b""),
                ("Stockfish/Copying.txt", b"GPL\n"),
            ),
            (
                ("Stockfish/src/main.cpp", b""),
                ("Stockfish/Copying.txt", b"GPL\n"),
            ),
        )
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "Stockfish-18-source.zip"
                _write_archive(archive_path, entries)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError, "does not contain source files"
                ):
                    _validate_stockfish_source_archive(archive_path, _limits())


    def test_validator_opens_zip_from_stable_snapshot_not_pathname(self):
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "Stockfish-18-source.zip"
            _write_archive(
                archive_path,
                (("Stockfish/src/main.cpp", b"// source fixture\n"),),
            )
            original_zipfile = zipfile.ZipFile
            with patch(
                "acs.version2_package_preflight.zipfile.ZipFile",
                wraps=original_zipfile,
            ) as wrapped:
                _validate_stockfish_source_archive(archive_path, _limits())
            self.assertTrue(wrapped.call_args_list)
            first_arg = wrapped.call_args_list[0].args[0]
            self.assertFalse(isinstance(first_arg, (str, Path)))

    def test_file_descendant_topology_collisions_fail_closed(self):
        cases = (
            (
                ("Stockfish/src", b"regular file\n"),
                ("Stockfish/src/main.cpp", b"child\n"),
            ),
            (
                ("Stockfish/SRC", b"regular file\n"),
                ("Stockfish/src/main.cpp", b"child\n"),
            ),
            (
                ("Stockfish/src/main.cpp", b"child\n"),
                ("Stockfish/src", b"regular file\n"),
            ),
        )
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "Stockfish-18-source.zip"
                _write_archive(archive_path, entries)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError, "topology collision"
                ):
                    _validate_stockfish_source_archive(archive_path, _limits())


if __name__ == "__main__":
    unittest.main()