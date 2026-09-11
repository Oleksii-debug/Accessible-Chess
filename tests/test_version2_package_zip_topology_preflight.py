from __future__ import annotations

from io import BytesIO
import tempfile
import unittest
import zipfile

from acs.version2_package_preflight import (
    PackageLimits,
    Version2PackagePreflightError,
    _validate_zip_entries,
)


def _archive(entries: tuple[tuple[str, bytes], ...]) -> zipfile.ZipFile:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as writer:
        for name, payload in entries:
            writer.writestr(name, payload)
    buffer.seek(0)
    archive = zipfile.ZipFile(buffer, "r")
    archive._accessible_chess_test_buffer = buffer  # keep backing bytes alive
    return archive


class Version2PackageZipTopologyPreflightTests(unittest.TestCase):
    def test_regular_sibling_files_are_accepted(self):
        with _archive(
            (
                ("AccessibleChess/assets/a.dat", b"a"),
                ("AccessibleChess/assets/b.dat", b"b"),
            )
        ) as archive:
            entries = _validate_zip_entries(archive, PackageLimits())
        self.assertEqual(len(entries), 2)

    def test_file_descendant_topology_collisions_fail_closed(self):
        cases = (
            (
                ("AccessibleChess/assets", b"regular file\n"),
                ("AccessibleChess/assets/data.bin", b"child\n"),
            ),
            (
                ("AccessibleChess/ASSETS", b"regular file\n"),
                ("accessiblechess/assets/data.bin", b"child\n"),
            ),
            (
                ("AccessibleChess/assets/data.bin", b"child\n"),
                ("AccessibleChess/assets", b"regular file\n"),
            ),
        )
        for entries in cases:
            with self.subTest(entries=entries), _archive(entries) as archive:
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "topology collision",
                ):
                    _validate_zip_entries(archive, PackageLimits())


if __name__ == "__main__":
    unittest.main()
