"""New Section37 original Réti composition: genuine bilingual endgame proof."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_reti_historical_bilingual_study as qa


class HistoricRetiOriginalStudyQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = qa.qualify_original_reti_study()

    def test_actual_historically_authored_composition_is_not_fabricated_training_game(self):
        r = self.receipt
        self.assertEqual(r["source_id"], qa.SOURCE_ID)
        self.assertEqual(r["source_bytes"], 2077)
        self.assertEqual(len(r["source_sha256"]), 64)
        self.assertEqual(r["historical_composition_year"], 1921)
        self.assertEqual(r["canonical_replayed_san_plies"], 11)
        self.assertEqual(r["original_fen"], qa.ORIGINAL_FEN)
        self.assertEqual(r["actual"]["original_annotation_languages"], ["uk", "en"])
        self.assertTrue(r["bilingual_english_ukrainian"])
        self.assertTrue(r["real_source_read"])
        self.assertFalse(r["mocked"])
        self.assertFalse(r["section39_terminal_done"])

    def test_real_composition_comments_are_preserved_through_pgn_and_library(self):
        actual = self.receipt["actual"]
        self.assertTrue(actual["full_game_tree_pgn_reimport_equal"])
        self.assertTrue(actual["full_game_tree_acsdb_restart_equal"])
        self.assertEqual(actual["source_search_count"], 1)
        self.assertEqual(self.receipt["qualification"], "PASS")

    def test_changed_source_or_bad_rights_cannot_be_called_authentic(self):
        raw_read = qa.read_verified_source_snapshot
        def damage(path, record):
            return raw_read(path, record)[:-1]
        with patch.object(qa, "read_verified_source_snapshot", side_effect=damage):
            with self.assertRaisesRegex(LawfulCorpusError, "bytes changed"):
                qa.qualify_original_reti_study()
        old = qa.load_catalog
        with patch.object(qa, "load_catalog", return_value=tuple(
            {**x, "public_release": "NOT_CLEARED"}
            if x["id"] == qa.SOURCE_ID else x for x in old()
        )):
            with self.assertRaisesRegex(LawfulCorpusError, "not proven"):
                qa.qualify_original_reti_study()


if __name__ == "__main__":
    unittest.main()
