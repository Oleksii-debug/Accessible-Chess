"""Original licensed TXT/Markdown/PDF Section 39 format-evidence safety contract."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.section39_external_book_semantic import IDS, qualify_external_books


class OriginalBookFormatTests(unittest.TestCase):
    def test_corpus_book_and_license_candidates_are_original_sources_only(self):
        records = {item["id"]: item for item in load_catalog()}
        self.assertEqual(len(IDS), 5)
        self.assertEqual(
            {records[item]["format"] for item in IDS},
            {"txt", "md", "pdf"},
        )
        for key in IDS:
            with self.subTest(source=key):
                entry = records[key]
                self.assertIn("external_checkout_path", entry)
                self.assertEqual(entry["public_release"] in
                                 {"EXCLUDED", "EXCLUDED_PENDING_QUALIFICATION"}, True)
                self.assertEqual(entry["acquisition"] in
                                 {"PINNED_NOT_DOWNLOADED_IN_THIS_PASS",
                                  "DISCOVERED_NOT_HASH_VERIFIED"}, True)
                self.assertIsNotNone(entry["upstream_git_blob"])

    def test_absent_license_and_original_bytes_prevent_any_real_pass(self):
        selected = tuple(x for x in load_catalog() if x["id"] in IDS)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(LawfulCorpusError):
                qualify_external_books(selected, root)
            for entry in selected:
                with self.subTest(source=entry["id"]):
                    path = root / entry["external_checkout_path"]
                    path.parent.mkdir(exist_ok=True, parents=True)
                    path.write_bytes(b"NOT AN ORIGINAL CHESS BOOK")
                    with self.assertRaises(LawfulCorpusError):
                        qualify_external_books(selected, root)
                    path.unlink()

    def test_missing_book_cannot_be_hidden_by_partial_catalog(self):
        selected = tuple(x for x in load_catalog() if x["id"] in IDS)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(LawfulCorpusError, "five actual external"):
                qualify_external_books(selected[:-1], Path(temp))


if __name__ == "__main__":
    unittest.main()
