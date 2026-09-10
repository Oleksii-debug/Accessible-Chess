from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from acs.sound_events import SoundEvent
from acs.version2_package_assembler import (
    Version2PackageAssemblyError,
    assemble_version2_package_tree,
    write_version2_package_zip,
)
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from acs.version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


_SHA = "a" * 40
_REQUIRED_WEB = (
    "index.html",
    "stage1_release_bootstrap.js",
    "stage1_board_actions.js",
    "full_product_pgn.js",
    "full_product_library.js",
    "full_product_books_training.js",
    "version2_release_bootstrap.js",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Version2PackageAssemblerTests(unittest.TestCase):
    def _sources(self, root: Path) -> tuple[Path, Path]:
        product = root / "prepared-product"
        notices = root / "third-party-notices"

        web = product / "web"
        web.mkdir(parents=True)
        (product / "AccessibleChess.exe").write_bytes(b"MZ\0v2-test")
        (product / "runtime.dll").write_bytes(b"runtime")
        for name in _REQUIRED_WEB:
            (web / name).write_text(f"// canonical fixture {name}\n", encoding="utf-8")

        sounds = product / "assets" / "sounds"
        sounds.mkdir(parents=True)
        sound_files: dict[str, str] = {}
        for event in SoundEvent:
            name = f"{event.value}.wav"
            sound_files[event.value] = name
            with wave.open(str(sounds / name), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x00\x00" * 16)
        (sounds / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "files": sound_files}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        engine = product / "engines" / "stockfish"
        engine.mkdir(parents=True)
        (engine / "stockfish.exe").write_bytes(b"MZ\x00Stockfish18")

        notices.mkdir()
        with zipfile.ZipFile(
            notices / "Stockfish-18-source.zip",
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("Stockfish-sf_18/src/main.cpp", "// source fixture\n")
            archive.writestr("Stockfish-sf_18/Copying.txt", "GNU GPL v3\n")
        (notices / "Stockfish-NOTICE.txt").write_text(
            "Stockfish 18\nLicense: GNU GPL v3\nComplete corresponding source is included.\n",
            encoding="utf-8",
        )
        return product, notices

    def test_assembles_fresh_tree_with_exact_manifest_and_checksums(self) -> None:
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
            self.assertTrue(
                (output / "THIRD_PARTY_NOTICES" / "Stockfish-18-source.zip").is_file()
            )
            manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_schema"], V2_PACKAGE_MANIFEST_SCHEMA_VERSION)
            self.assertEqual(manifest["package_profile"], V2_PACKAGE_PROFILE)
            self.assertEqual(manifest["integration_sha"], _SHA)
            self.assertEqual(manifest["upgrade_journal_schema"], UPGRADE_JOURNAL_SCHEMA_VERSION)
            self.assertEqual(manifest["settings_schema"], SETTINGS_SCHEMA_VERSION)
            self.assertEqual(manifest["acsdb_schema"], ACSDB_SCHEMA_VERSION)
            self.assertIs(manifest["nvda_verified"], False)
            self.assertIs(manifest["user_data_bundled"], False)
            self.assertIs(manifest["raw_source_bundled"], False)
            self.assertIs(manifest["optional_external_backends_bundled"], False)

            rows = (output / CHECKSUMS_NAME).read_text(encoding="utf-8").splitlines()
            paths = [row.split("  ", 1)[1] for row in rows]
            self.assertEqual(paths, sorted(paths, key=str.casefold))
            self.assertNotIn(CHECKSUMS_NAME, paths)
            for row in rows:
                digest, relative = row.split("  ", 1)
                self.assertEqual(
                    digest,
                    _sha256(output.joinpath(*relative.split("/"))),
                    relative,
                )

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
                (output / "native-menu-self-diagnostic.json").read_bytes(), native.read_bytes()
            )
            self.assertEqual(
                (output / "packaged-uia-strict-summary.json").read_bytes(), uia.read_bytes()
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

    def test_user_data_and_raw_source_leaks_fail_before_publication(self) -> None:
        cases = (
            ("settings.json", b"{}\n", "user state is forbidden"),
            ("library.acsdb", b"private", "user state is forbidden"),
            ("debug.py", b"print('leak')\n", "raw source is forbidden"),
        )
        for name, payload, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                product, notices = self._sources(root)
                (product / name).write_bytes(payload)
                output = root / "candidate"

                with self.assertRaisesRegex(Exception, expected):
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

    def test_output_created_after_preflight_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"

            def validate_then_race(staged: Path, **kwargs):
                report = validate_version2_package_tree(staged, **kwargs)
                output.mkdir()
                (output / "keep.txt").write_text("keep", encoding="utf-8")
                return report

            with patch(
                "acs.version2_package_assembler.validate_version2_package_tree",
                side_effect=validate_then_race,
            ):
                with self.assertRaisesRegex(
                    Version2PackageAssemblyError,
                    "appeared during assembly",
                ):
                    assemble_version2_package_tree(
                        product,
                        notices,
                        output,
                        integration_sha=_SHA,
                    )
            self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")

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
                timestamps = {entry.date_time for entry in archive.infolist()}
            self.assertEqual(names, sorted(names, key=str.casefold))
            self.assertEqual(timestamps, {(1980, 1, 1, 0, 0, 0)})
            self.assertIn("AccessibleChess/AccessibleChess.exe", names)
            self.assertIn(MANIFEST_NAME, names)
            self.assertIn(CHECKSUMS_NAME, names)

    def test_zip_output_race_does_not_overwrite_existing_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            product, notices = self._sources(root)
            output = root / "candidate"
            assemble_version2_package_tree(product, notices, output, integration_sha=_SHA)
            target = root / "candidate.zip"

            def validate_then_race(archive: Path, **kwargs):
                report = validate_version2_package_zip(archive, **kwargs)
                target.write_bytes(b"keep")
                return report

            with patch(
                "acs.version2_package_assembler.validate_version2_package_zip",
                side_effect=validate_then_race,
            ):
                with self.assertRaisesRegex(
                    Version2PackageAssemblyError,
                    "appeared during assembly",
                ):
                    write_version2_package_zip(
                        output,
                        target,
                        expected_integration_sha=_SHA,
                    )
            self.assertEqual(target.read_bytes(), b"keep")

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
