from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_package_assembler import _write_checksums
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
)
from acs.version2_portable_package import (
    PORTABLE_PACKAGE_PROFILE,
    PORTABLE_SOURCE_CHECKSUMS,
    PORTABLE_SOURCE_MANIFEST,
    PORTABLE_SOURCE_METADATA_DIR,
    Version2PortablePackageError,
    assemble_portable_oneclick_tree,
    validate_portable_oneclick_tree,
    write_portable_oneclick_zip,
)


_SHA = "a" * 40


def _pe(path: Path, size: int = 2048) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * (size - 2))


def _portable_fixture(root: Path, *, with_seed: bool = False) -> None:
    _pe(root / "AccessibleChess.exe")
    _pe(root / "App" / "AccessibleChess.exe")
    (root / "App" / "AccessibleChess.exe.config").write_text("<configuration />", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES").mkdir(parents=True)
    (root / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text("test notice", encoding="utf-8")
    (root / "Посібник.docx").write_bytes(b"doc-one")
    (root / "Опис.docx").write_bytes(b"doc-two")
    if with_seed:
        seed = root / "App" / "release-content" / "user-library-seed"
        seed.mkdir(parents=True)
        (seed / "manifest.json").write_text("{}", encoding="utf-8")
    source_metadata = root / PORTABLE_SOURCE_METADATA_DIR
    source_metadata.mkdir()
    source_manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": _SHA,
    }
    source_manifest_path = source_metadata / MANIFEST_NAME
    source_manifest_path.write_text(
        json.dumps(source_manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_entries = {
        MANIFEST_NAME: hashlib.sha256(source_manifest_path.read_bytes()).hexdigest(),
    }
    for path in (root / "App").rglob("*"):
        if path.is_file():
            relative = "AccessibleChess/" + path.relative_to(root / "App").as_posix()
            source_entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (root / "THIRD_PARTY_NOTICES").rglob("*"):
        if path.is_file():
            relative = "THIRD_PARTY_NOTICES/" + path.relative_to(root / "THIRD_PARTY_NOTICES").as_posix()
            source_entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    source_checksums_path = source_metadata / CHECKSUMS_NAME
    source_checksums_path.write_text(
        "".join(
            f"{digest}  {relative}\n"
            for relative, digest in sorted(source_entries.items())
        ),
        encoding="utf-8",
    )

    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": PORTABLE_PACKAGE_PROFILE,
        "source_package_profile": V2_PACKAGE_PROFILE,
        "source_manifest": PORTABLE_SOURCE_MANIFEST,
        "source_manifest_sha256": hashlib.sha256(source_manifest_path.read_bytes()).hexdigest(),
        "source_checksums": PORTABLE_SOURCE_CHECKSUMS,
        "source_checksums_sha256": hashlib.sha256(source_checksums_path.read_bytes()).hexdigest(),
        "integration_sha": _SHA,
        "launcher": "AccessibleChess.exe",
        "application_directory": "App",
        "application_executable": "App/AccessibleChess.exe",
        "package_local_appdata": "data/AccessibleChess",
        "launch_report": "launch-report.txt",
        "word_documents": ["Посібник.docx", "Опис.docx"],
        "human_tested": False,
        "nvda_verified": False,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_checksums(root)


class PortableTreeTests(unittest.TestCase):
    def test_accepts_exact_oneclick_topology_without_prebundled_user_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            report = validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)
            self.assertEqual(report.integration_sha, _SHA)
            self.assertIn("AccessibleChess.exe", report.inventory)
            self.assertIn("App/AccessibleChess.exe", report.inventory)
            self.assertNotIn("launch-report.txt", report.inventory)
            self.assertFalse((root / "data").exists())

    def test_rejects_bundled_mutable_data_and_stale_launch_report(self):
        for relative in (Path("data") / "AccessibleChess" / "library.acsdb", Path("launch-report.txt")):
            with self.subTest(relative=str(relative)), tempfile.TemporaryDirectory() as raw:
                root = Path(raw) / "portable"
                root.mkdir()
                _portable_fixture(root)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"stale")
                _write_checksums(root)
                with self.assertRaises(Version2PortablePackageError):
                    validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_requires_exact_declared_two_root_docx_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "extra.docx").write_bytes(b"unexpected")
            _write_checksums(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "exactly the declared two"):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_rejects_any_undeclared_root_file_even_if_checksummed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "unexpected.txt").write_text("not part of the user package contract", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "unexpected file"):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_checksum_readback_detects_post_assembly_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "App" / "AccessibleChess.exe.config").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "preflighted canonical source|checksum verification",
            ):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_rejects_inner_mutation_even_if_outer_checksums_are_rewritten(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "App" / "AccessibleChess.exe.config").write_text(
                "changed",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "preflighted canonical source",
            ):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_private_seed_requirement_is_explicit_and_package_local(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root, with_seed=True)
            report = validate_portable_oneclick_tree(
                root,
                expected_integration_sha=_SHA,
                require_user_seed=True,
            )
            self.assertGreater(report.total_bytes, 0)

    def test_assembler_reuses_canonical_inner_payload_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "AccessibleChess" / "payload.dat").write_bytes(b"canonical-product-bytes")
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text("notice", encoding="utf-8")
            canonical_manifest = {
                "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                "product": "Accessible Chess",
                "package_profile": V2_PACKAGE_PROFILE,
                "integration_sha": _SHA,
            }
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(canonical_manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)
            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            output = work / "portable"

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                return_value=object(),
            ) as canonical_validation:
                report = assemble_portable_oneclick_tree(
                    canonical,
                    launcher,
                    (first, second),
                    output,
                    integration_sha=_SHA,
                )

            canonical_validation.assert_called_once_with(canonical, expected_integration_sha=_SHA)
            self.assertEqual((output / "App" / "payload.dat").read_bytes(), b"canonical-product-bytes")
            self.assertEqual((output / "AccessibleChess.exe").read_bytes(), launcher.read_bytes())
            self.assertTrue((output / PORTABLE_SOURCE_METADATA_DIR / MANIFEST_NAME).is_file())
            self.assertTrue((output / PORTABLE_SOURCE_METADATA_DIR / CHECKSUMS_NAME).is_file())
            self.assertFalse((output / "data").exists())
            self.assertEqual(report.integration_sha, _SHA)

    def test_zip_is_deterministic_and_byte_verified(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            first = write_portable_oneclick_zip(root, work / "first.zip", expected_integration_sha=_SHA)
            second = write_portable_oneclick_zip(root, work / "second.zip", expected_integration_sha=_SHA)
            self.assertEqual(first.archive_sha256, second.archive_sha256)
            self.assertEqual((work / "first.zip").read_bytes(), (work / "second.zip").read_bytes())
            self.assertNotIn(CHECKSUMS_NAME + "/", first.inventory)

    def test_zip_output_cannot_mutate_the_package_tree(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "outside the package tree"):
                write_portable_oneclick_zip(
                    root,
                    root / "candidate.zip",
                    expected_integration_sha=_SHA,
                )
            self.assertFalse((root / "candidate.zip").exists())


if __name__ == "__main__":
    unittest.main()
