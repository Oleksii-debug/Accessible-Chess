"""Offline, non-copying inventory of genuine vendored CC0 chess-source bytes.

This checks source/license integrity for an explicitly authorized test inventory.
It does not claim any source has been semantically imported into Books/Library,
or that a proprietary ChessBase file has been qualified or redistributed.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import (
    LawfulCorpusError,
    inventory_vendored_corpus,
    load_catalog,
)


ROOT = Path(__file__).resolve().parents[1]


class OfflineCorpusInventoryTests(unittest.TestCase):
    def test_actual_upstream_corpora_have_byte_verified_test_inventory(self):
        records = load_catalog()
        inventory = inventory_vendored_corpus(records, ROOT, distribution="TEST_BUILD")
        ids = {row["source_id"] for row in inventory}
        self.assertEqual(len(inventory), 9)
        self.assertEqual(
            len([name for name in ids if name.startswith("lichess_openings_original_")]), 5
        )
        self.assertEqual(
            len([name for name in ids if name.startswith("stockfish_")]), 4
        )
        self.assertTrue(all(row["bytes"] > 0 for row in inventory))
        self.assertTrue(
            all(row["semantic_state"] == "VERIFIED_BYTES_NOT_IMPORTED" for row in inventory)
        )
        self.assertFalse(any("gitenberg" in name or "chessbase" in name for name in ids))

    def test_public_index_is_stricter_than_owner_test_inventory(self):
        records = load_catalog()
        trial = inventory_vendored_corpus(records, ROOT, distribution="TEST_BUILD")
        public = inventory_vendored_corpus(records, ROOT, distribution="PUBLIC_RELEASE")
        self.assertEqual(len(trial), 9)
        self.assertEqual(len(public), 5)
        self.assertTrue(all(row["source_id"].startswith("lichess_openings_original_") for row in public))
        self.assertTrue(all(row["distribution"] == "PUBLIC_RELEASE" for row in public))
        self.assertFalse(any(row["format"] in ("cbv", "cbh", "txt") for row in public))

    def test_unqualified_original_book_and_chessbase_are_not_release_content(self):
        records = load_catalog()
        book = next(item for item in records if item["id"] == "gitenberg_capablanca_33870_original_txt")
        chessbase = next(
            item for item in records
            if item["id"] == "chessbase_official_free_rossolimo_cbv_sample"
        )
        for distribution in ("TEST_BUILD", "PUBLIC_RELEASE"):
            self.assertEqual(
                inventory_vendored_corpus((book, chessbase), ROOT, distribution=distribution),
                (),
            )

    def test_traversal_and_missing_source_cannot_be_inventoried(self):
        source = next(
            item for item in load_catalog()
            if item["id"] == "lichess_openings_original_eco_a_tsv"
        )
        for candidate in (
            "../outside.tsv",
            "tests/real_corpus/../other.txt",
            "tests/real_corpus/../../secrets.txt",
            "tests\\real_corpus\\lichess_openings_a.tsv",
            "/tests/real_corpus/lichess_openings_a.tsv",
            "tests/real_corpus/absent.tsv",
        ):
            with self.subTest(path=candidate):
                with self.assertRaises(LawfulCorpusError):
                    inventory_vendored_corpus(
                        ({**source, "local_source": candidate},),
                        ROOT,
                        distribution="TEST_BUILD",
                    )

    def test_false_source_checksum_and_license_are_refused(self):
        source = next(
            item for item in load_catalog()
            if item["id"] == "lichess_openings_original_eco_a_tsv"
        )
        for modified in (
            {"sha256": "0" * 64},
            {"license_sha256": "0" * 64},
            {"max_bytes": 1},
        ):
            with self.subTest(modified=modified):
                with self.assertRaises(LawfulCorpusError):
                    inventory_vendored_corpus(
                        ({**source, **modified},), ROOT, distribution="TEST_BUILD"
                    )

    def test_unqualified_distribution_and_duplicate_ids_fail_closed(self):
        source = next(
            item for item in load_catalog()
            if item["id"] == "lichess_openings_original_eco_a_tsv"
        )
        with self.assertRaises(LawfulCorpusError):
            inventory_vendored_corpus((source,), ROOT, distribution="anything")
        with self.assertRaises(LawfulCorpusError):
            inventory_vendored_corpus((source, source), ROOT, distribution="TEST_BUILD")

    def test_intermediate_symlink_is_not_a_trusted_fixture_root(self):
        source = next(
            item for item in load_catalog()
            if item["id"] == "lichess_openings_original_eco_a_tsv"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixtures = root / "tests"
            try:
                fixtures.symlink_to(ROOT / "tests", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation prohibited by test host")
            with self.assertRaisesRegex(LawfulCorpusError, "indirect"):
                inventory_vendored_corpus((source,), root, distribution="TEST_BUILD")


if __name__ == "__main__":
    unittest.main()
