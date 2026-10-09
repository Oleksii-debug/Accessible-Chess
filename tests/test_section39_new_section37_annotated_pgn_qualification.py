"""Section 39 coverage of newly vendored genuine Section 37 annotated sources."""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError
from tools.section39_new_section37_annotated_pgn_qualification import (
    SOURCE, qualify_new_section37_original,
)


class OriginalSection37GameQualificationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = qualify_new_section37_original()

    def test_actual_original_source_does_not_get_counted_as_mock(self):
        self.assertEqual(self.receipt["source_id"], SOURCE)
        self.assertEqual(self.receipt["original_game_count"], 4)
        self.assertTrue(self.receipt["real_source_read"])
        self.assertFalse(self.receipt["mocked"])
        self.assertEqual(len(self.receipt["original_sha256"]), 64)
        self.assertEqual(self.receipt["original_bytes"], 20121)

    def test_real_chess_source_annotations_and_roundtrip_readbacks(self):
        actual = self.receipt["actual"]
        self.assertEqual(actual["imported_games"], 4)
        self.assertEqual(actual["search_result_games"], 4)
        self.assertEqual(actual["source_indexes"], [0, 1, 2, 3])
        self.assertTrue(actual["full_game_tree_equal_after_pgn_export"])
        self.assertTrue(actual["full_game_tree_equal_after_acsdb_restart"])
        self.assertEqual(self.receipt["qualification"], "PASS")
        self.assertFalse(self.receipt["section39_terminal_done"])

    def test_mutated_original_source_fails_before_canonical_parser(self):
        from tools import section39_new_section37_annotated_pgn_qualification as module
        genuine = module.read_verified_source_snapshot
        def damaged(path, record):
            return genuine(path, record)[:-1]
        with patch.object(module, "read_verified_source_snapshot", side_effect=damaged):
            with self.assertRaisesRegex(LawfulCorpusError, "identity mismatch"):
                qualify_new_section37_original()

    def test_wrong_manifest_or_extracted_source_cannot_fake_real_readback(self):
        from tools import section39_new_section37_annotated_pgn_qualification as module
        original = module.load_catalog
        def wrong_catalog(*args, **kwargs):
            recs = original(*args, **kwargs)
            return tuple({**r, "redistribution": "NOT_CLEARED"} if r["id"] == SOURCE else r
                         for r in recs)
        with patch.object(module, "load_catalog", side_effect=wrong_catalog):
            with self.assertRaisesRegex(LawfulCorpusError, "missing or unlicensed"):
                qualify_new_section37_original()


if __name__ == "__main__":
    import unittest
    unittest.main()
