from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from acs.version2_package_preflight import (
    Version2PackagePreflightError,
    validate_version2_package_zip,
)


_SHA = "a" * 40


class Version2PackagePreflightWindowsDeviceAliasTests(unittest.TestCase):
    def test_superscript_com_lpt_aliases_fail_before_zip_readback(self) -> None:
        reserved = (
            "COM¹.txt",
            "com².bin",
            "Com³.dat",
            "LPT¹.txt",
            "lpt².bin",
            "Lpt³.dat",
        )
        for name in reserved:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "hostile.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(f"AccessibleChess/{name}", b"hostile")

                with patch(
                    "acs.version2_package_preflight.tempfile.TemporaryDirectory",
                    side_effect=AssertionError("ZIP readback must not start"),
                ):
                    with self.assertRaisesRegex(
                        Version2PackagePreflightError,
                        "reserved Windows name",
                    ):
                        validate_version2_package_zip(
                            archive_path,
                            expected_integration_sha=_SHA,
                        )


if __name__ == "__main__":
    unittest.main()
