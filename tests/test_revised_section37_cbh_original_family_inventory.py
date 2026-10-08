"""Source-only original GPL ChessBase companion acquisition regression checks.

A synthetic temporary fixture here tests parser-independent security boundaries.
The dedicated live CI job checks the actual upstream libcbh GPL files and PGN
oracle bytes separately, at a pinned Git revision.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_cbh_original_family_inventory import (
    UPSTREAM_COMMIT, SUFFIXES, _raw_git_blob,
    original_cbh_source_receipts, verify_gpl_cbh_family,
)

EXPECTED = {
    "libcbh_gpl_original_annotation_cbh_family": "TestBase",
    "libcbh_gpl_original_nested_variations_cbh_family": "WithVariations",
    "libcbh_gpl_original_unusual_start_cbh_family": "UnusualStartBytes",
}
LICENSE = b"                    GNU GENERAL PUBLIC LICENSE\nfixture for negative unit testing"
ORACLE = b'[Event "Test"]\n\n1. e4 *\n'


def sample_fixture(root: Path) -> dict:
    (root / "gtest/Annotation").mkdir(parents=True)
    (root / "LICENSE").write_bytes(LICENSE)
    record = {
        "id": "libcbh_sample_test",
        "source_page": "https://github.com/rolandlo/libcbh",
        "format": "cbh (multifile original companion family)",
        "upstream_commit": UPSTREAM_COMMIT,
        "test_access": "EXTERNAL_GPL_EPHEMERAL_ONLY",
        "public_release": "EXCLUDED",
        "redistribution": "NOT_CLEARED",
        "external_fixture_directory": "Annotation",
        "external_fixture_stem": "Sample",
        "external_oracle_filename": "Reference.pgn",
        "external_oracle_git_blob": _raw_git_blob(ORACLE),
        "external_license_git_blob": _raw_git_blob(LICENSE),
        "external_companion_git_blobs": {},
    }
    for ext in sorted(SUFFIXES):
        name = "Sample" + ext
        data = ("original test-only companion " + name).encode()
        (root / "gtest/Annotation" / name).write_bytes(data)
        record["external_companion_git_blobs"][name] = _raw_git_blob(data)
    (root / "gtest/Annotation/Reference.pgn").write_bytes(ORACLE)
    return record


class OriginalGPLCompanionTests(unittest.TestCase):
    def test_three_actual_external_cbh_families_are_pinned_not_reported_as_imported(self):
        catalog = {item["id"]: item for item in load_catalog()}
        self.assertEqual(_raw_git_blob(b"test"), "30d74d258442c7c65512eafab474568dd706c430")
        for identity, stem in EXPECTED.items():
            with self.subTest(source=identity):
                entry = catalog[identity]
                self.assertEqual(entry["upstream_commit"], UPSTREAM_COMMIT)
                self.assertEqual(entry["external_fixture_stem"], stem)
                self.assertEqual(entry["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(entry["redistribution"], "NOT_CLEARED")
                self.assertEqual(entry["public_release"], "EXCLUDED")
                self.assertEqual(entry["external_license_git_blob"], "d159169d1050894d3ea3b98e1c965c4058208fe1")
                companions = entry["external_companion_git_blobs"]
                self.assertEqual(len(companions), 11)
                self.assertEqual(set(companions), {stem + ext for ext in SUFFIXES})
                self.assertTrue(all(len(digest) == 40 for digest in companions.values()))
                self.assertEqual(len(entry["external_oracle_git_blob"]), 40)

    def test_original_complete_source_family_verified_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = sample_fixture(root)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
            result = verify_gpl_cbh_family(record, root)
            self.assertEqual(result["original_companion_count"], 11)
            self.assertEqual(len(result["original_companions"]), 11)
            self.assertEqual(result["semantic_import"], "NOT_TESTED_BY_SOURCE_ACQUISITION")
            self.assertEqual(result["public_release"], "EXCLUDED")
            self.assertEqual(
                sorted(p.relative_to(root).as_posix() for p in root.rglob("*")), before
            )

    def test_missing_damaged_extra_companion_and_license_are_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = sample_fixture(root)
            family = root / "gtest/Annotation"
            bad_cases = (
                (family / "Sample.cbg", b"bad"),
                (root / "LICENSE", b"replacement license"),
                (family / "Reference.pgn", b"bad oracle"),
            )
            for target, corrupt in bad_cases:
                with self.subTest(target=target.name):
                    original = target.read_bytes()
                    target.write_bytes(corrupt)
                    with self.assertRaises(LawfulCorpusError):
                        verify_gpl_cbh_family(record, root)
                    target.write_bytes(original)
            (family / "Sample.cbt").unlink()
            with self.assertRaises(LawfulCorpusError):
                verify_gpl_cbh_family(record, root)
            (family / "Sample.cbt").write_bytes(b"original test-only companion Sample.cbt")
            (family / "Sample.cbn").write_bytes(b"unexpected companion")
            with self.assertRaises(LawfulCorpusError):
                verify_gpl_cbh_family(record, root)
            # A genuinely unexpected additional family extension must not be
            # erased or interpreted as a successful complete-source inventory.
            altered = {**record, "external_companion_git_blobs": {"bogus.cbh": "0" * 40}}
            with self.assertRaises(LawfulCorpusError):
                verify_gpl_cbh_family(altered, root)

    def test_source_path_symlink_and_source_rights_spoofs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = sample_fixture(root)
            with self.assertRaises(LawfulCorpusError):
                original_cbh_source_receipts((record,), root)
            for tamper in (
                {"redistribution": "permitted"},
                {"public_release": "INCLUDED"},
                {"test_access": "PUBLIC"},
                {"external_fixture_directory": "../outside"},
                {"external_fixture_stem": "Other"},
                {"external_oracle_git_blob": "0" * 40},
                {"upstream_commit": "0" * 40},
            ):
                with self.subTest(tamper=tamper):
                    with self.assertRaises(LawfulCorpusError):
                        verify_gpl_cbh_family({**record, **tamper}, root)
            target = root / "gtest/Annotation/Sample.cba"
            target.unlink()
            try:
                target.symlink_to(root / "gtest/Annotation/Sample.cbg")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on host")
            with self.assertRaises(LawfulCorpusError):
                verify_gpl_cbh_family(record, root)


if __name__ == "__main__":
    unittest.main()
