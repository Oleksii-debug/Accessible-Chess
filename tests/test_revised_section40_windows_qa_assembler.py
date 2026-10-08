"""Section 40 no-owner-overwrite executable-package composition qualification.

Uses EXISTING Windows Version 2 prepared-package fixtures and the canonical
assembler: a structurally valid synthetic PE is not an actual installed EXE.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from acs.user_library_seed import BUNDLE_KIND, SCHEMA_VERSION
from tests.test_version2_package_preflight import _make_tree, _SHA
from tools.revised_section40_offline_test_library import (
    OfflineCollectionError, build_collection,
)
from tools.revised_section40_windows_qa_assembler import (
    build_section40_windows_test_package,
)

ROOT = Path(__file__).resolve().parents[1]


def _prepared_fixture(work: Path) -> tuple[Path, Path]:
    original = work / "prepared-original"
    original.mkdir()
    _make_tree(original)
    product = original / "AccessibleChess"
    # Do not use a fake unstyled HTML: exercise actual Section41 offline
    # assets together with the real Section40 Windows package contract.
    for relative in (
        "web/index.html",
        "web/assets/accessible_chess_design.css",
        "web/assets/tabler/chess-rook.svg",
        "web/assets/tabler/adjustments.svg",
        "web/assets/tabler/LICENSE",
        "web/assets/tabler/SECTION41_PROVENANCE.json",
        "web/assets/tabler-core/accessibility.css",
        "web/assets/tabler-core/LICENSE",
        "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json",
    ):
        destination = product / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return product, original / "THIRD_PARTY_NOTICES"


class Section40RealWindowsQAPackageTests(unittest.TestCase):
    def test_actual_canonical_windows_package_assembles_and_reimports_516(self):
        with tempfile.TemporaryDirectory(prefix="section40-canonical-win-") as temp:
            root = Path(temp)
            product, notices = _prepared_fixture(root)
            collection = root / "licensed-corpus.zip"
            output = root / "owner-test.zip"
            build_collection("TEST_BUILD", collection)
            before = hashlib.sha256(
                (product / "web/index.html").read_bytes()
            ).hexdigest()
            report = build_section40_windows_test_package(
                product, notices, collection, output, exact_source_sha=_SHA)
            self.assertEqual(report["seed_sources"], 2)
            self.assertEqual(report["seed_games"], 516)
            self.assertEqual(report["restart_reused_sources"], 2)
            self.assertEqual(report["original_seed_files_untouched"], 0)
            self.assertTrue(report["canonical_version2_package_readback"])
            self.assertFalse(report["compiled_real_exe_attested"])
            self.assertFalse(report["section40_done"])
            self.assertEqual(before, hashlib.sha256(
                (product / "web/index.html").read_bytes()).hexdigest())
            with zipfile.ZipFile(output) as archive:
                members = set(archive.namelist())
                self.assertIn("AccessibleChess/web/assets/tabler-core/LICENSE", members)
                self.assertIn("AccessibleChess/web/assets/accessible_chess_design.css", members)
                self.assertIn(
                    "AccessibleChess/release-content/user-library-seed/manifest.json",
                    members,
                )
                manifest = json.loads(archive.read(
                    "AccessibleChess/release-content/user-library-seed/manifest.json"))
                self.assertEqual(len(manifest["files"]), 2)
                self.assertEqual(manifest["bundle_kind"], BUNDLE_KIND)
                self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)

    def test_public_only_archive_must_not_become_rich_windows_test_build(self):
        with tempfile.TemporaryDirectory(prefix="section40-public-win-refuse-") as temp:
            root = Path(temp)
            product, notices = _prepared_fixture(root)
            collection = root / "public-corpus.zip"
            build_collection("PUBLIC_RELEASE", collection)
            target = root / "must-not-exist.zip"
            with self.assertRaises(OfflineCollectionError):
                build_section40_windows_test_package(
                    product, notices, collection, target, exact_source_sha=_SHA)
            self.assertFalse(target.exists())

    def test_owner_zip_no_overwrite_even_if_data_not_yet_checked(self):
        with tempfile.TemporaryDirectory(prefix="section40-output-guard-") as temp:
            root = Path(temp)
            target = root / "owner-test.zip"
            target.write_bytes(b"existing user archive")
            with self.assertRaises(OfflineCollectionError):
                build_section40_windows_test_package(
                    root / "missing-product", root / "missing-notices",
                    root / "missing-corpus", target, exact_source_sha=_SHA)
            self.assertEqual(target.read_bytes(), b"existing user archive")


if __name__ == "__main__":
    unittest.main()
