from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.version2_package_assembler import (
    Version2PackageAssemblyError,
    assemble_version2_package_tree,
    write_version2_package_zip,
)
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    validate_version2_package_tree,
    validate_version2_package_zip,
)


_SHA = "a" * 40


class Version2PackageAssemblerTests(unittest.TestCase):
    def _sources(self, root: Path) -> tuple[Path, Path]:
        product = root / "prepared-product"
        notices = root / "notices"
        (product / "web").mkdir(parents=True)
        (product / "AccessibleChess.exe").write_bytes(b"MZ\0v2-test")
        (product / "runtime.dll").write_bytes(b"runtime")
        (product / "web" / "index.html").write_text("<main>Accessible Chess</main>\n", encoding="utf-8")
        notices.mkdir()
        (notices / "NOTICE.txt").write_text("Third-party notices\n", encoding="utf-8")
        return product, notices

    def test_assembles_fresh_tree_manifest_checksums_and_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"

            assembled = assemble_version2_package_tree(
                product,
                notices,
                output,
                integration_sha=_SHA,
            )

            self.assertEqual(assembled.package_root, output)
            self.assertEqual(assembled.tree_report.integration_sha, _SHA)
            self.assertTrue((output / "AccessibleChess" / "AccessibleChess.exe").is_file())
            self.assertTrue((output / "THIRD_PARTY_NOTICES" / "NOTICE.txt").is_file())
            manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["integration_sha"], _SHA)
            self.assertIs(manifest["nvda_verified"], False)
            self.assertIs(manifest["user_data_bundled"], False)
            self.assertIs(manifest["raw_source_bundled"], False)
            self.assertIs(manifest["optional_external_backends_bundled"], False)
            checksum_text = (output / CHECKSUMS_NAME).read_text(encoding="utf-8")
            self.assertIn("AccessibleChess/AccessibleChess.exe", checksum_text)
            self.assertNotIn(f"  {CHECKSUMS_NAME}\n", checksum_text)
            replay = validate_version2_package_tree(output, expected_integration_sha=_SHA)
            self.assertEqual(replay.inventory, assembled.tree_report.inventory)

    def test_diagnostic_evidence_uses_only_canonical_top_level_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            native = root / "native.json"
            uia = root / "uia.json"
            native.write_text('{"result":"PASS"}\n', encoding="utf-8")
            uia.write_text('{"result":"PASS"}\n', encoding="utf-8")
            output = root / "candidate"

            assemble_version2_package_tree(
                product,
                notices,
                output,
                integration_sha=_SHA,
                diagnostic_files={
                    "native-menu-self-diagnostic.json": native,
                    "packaged-uia-strict-summary.json": uia,
                },
            )
            self.assertEqual(
                (output / "native-menu-self-diagnostic.json").read_bytes(),
                native.read_bytes(),
            )
            self.assertEqual(
                (output / "packaged-uia-strict-summary.json").read_bytes(),
                uia.read_bytes(),
            )

            other = root / "other"
            with self.assertRaisesRegex(
                Version2PackageAssemblyError,
                "diagnostic file name is not allowed",
            ):
                assemble_version2_package_tree(
                    product,
                    notices,
                    other,
                    integration_sha=_SHA,
                    diagnostic_files={"debug.json": native},
                )
            self.assertFalse(other.exists())

    def test_preflight_failure_never_publishes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            (product / "settings.json").write_text("{}\n", encoding="utf-8")
            output = root / "candidate"

            with self.assertRaisesRegex(Exception, "user state is forbidden"):
                assemble_version2_package_tree(
                    product,
                    notices,
                    output,
                    integration_sha=_SHA,
                )
            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".accessible-chess-v2-assemble-*")))

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(Version2PackageAssemblyError, "must not already exist"):
                assemble_version2_package_tree(
                    product,
                    notices,
                    output,
                    integration_sha=_SHA,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_symlink_in_prepared_product_fails_closed_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            link = product / "runtime-link.dll"
            try:
                link.symlink_to(product / "runtime.dll")
            except OSError:
                self.skipTest("symlink creation is unavailable on this runner")
            output = root / "candidate"

            with self.assertRaisesRegex(
                Version2PackageAssemblyError,
                "symlink or reparse point",
            ):
                assemble_version2_package_tree(
                    product,
                    notices,
                    output,
                    integration_sha=_SHA,
                )
            self.assertFalse(output.exists())

    def test_zip_is_read_back_before_publish_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"
            assemble_version2_package_tree(
                product,
                notices,
                output,
                integration_sha=_SHA,
            )
            first = root / "candidate-a.zip"
            second = root / "candidate-b.zip"

            report_a = write_version2_package_zip(
                output,
                first,
                expected_integration_sha=_SHA,
            )
            report_b = write_version2_package_zip(
                output,
                second,
                expected_integration_sha=_SHA,
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(report_a.archive_sha256, report_b.archive_sha256)
            self.assertEqual(
                validate_version2_package_zip(first, expected_integration_sha=_SHA).archive_sha256,
                report_a.archive_sha256,
            )
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
            self.assertEqual(names, sorted(names, key=str.casefold))
            self.assertIn("AccessibleChess/AccessibleChess.exe", names)
            self.assertIn(MANIFEST_NAME, names)
            self.assertIn(CHECKSUMS_NAME, names)

    def test_zip_output_inside_package_and_existing_zip_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"
            assemble_version2_package_tree(product, notices, output, integration_sha=_SHA)

            with self.assertRaisesRegex(Version2PackageAssemblyError, "outside the package tree"):
                write_version2_package_zip(
                    output,
                    output / "bad.zip",
                    expected_integration_sha=_SHA,
                )

            existing = root / "existing.zip"
            existing.write_bytes(b"keep")
            with self.assertRaisesRegex(Version2PackageAssemblyError, "must not already exist"):
                write_version2_package_zip(
                    output,
                    existing,
                    expected_integration_sha=_SHA,
                )
            self.assertEqual(existing.read_bytes(), b"keep")

    def test_invalid_integration_sha_fails_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"
            for value in ("abc", "g" * 40, True):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(Version2PackageAssemblyError, "40-hex"):
                        assemble_version2_package_tree(
                            product,
                            notices,
                            output,
                            integration_sha=value,  # type: ignore[arg-type]
                        )
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
