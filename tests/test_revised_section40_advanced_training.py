"""Section 40 genuine-source advanced Training/Books integration regression."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Exercise
from acs.chesscore import Board, parse_sq
from acs.lawful_corpus_registry import LawfulCorpusError
from tools import revised_section40_advanced_training as advance


class AdvancedSection40RealContentTests(unittest.TestCase):
    def test_sixteen_genuine_2200_plus_are_canonical_playable_positions(self):
        assets, rows = advance.build_advanced_training()
        self.assertEqual(set(assets), {
            "books/advanced-lichess-16-middlegame-endgame.json",
            "training/advanced-lichess-16-middlegame-endgame.json",
        })
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(x["license"] == "CC0-1.0" for x in rows))
        book = BookDocument.from_dict(json.loads(
            assets["books/advanced-lichess-16-middlegame-endgame.json"]))
        tasks = json.loads(
            assets["training/advanced-lichess-16-middlegame-endgame.json"])["tasks"]
        exercises = [x for x in book.blocks if isinstance(x, Exercise)]
        self.assertEqual(len(tasks), 16)
        self.assertEqual(len(exercises), 16)
        self.assertTrue(all(x["puzzle_rating_lichess_not_fide"] >= 2200 for x in tasks))
        self.assertTrue(any(x["puzzle_rating_lichess_not_fide"] >= 2600 for x in tasks))
        self.assertFalse(any(x["puzzle_rating_lichess_not_fide"] >= 3000 for x in tasks))
        self.assertTrue(any("endgame" in x["themes"] for x in tasks))
        self.assertTrue(any("middlegame" in x["themes"] for x in tasks))
        for exercise, task in zip(exercises, tasks):
            self.assertEqual(exercise.fen, task["fen"])
            self.assertEqual(exercise.answer_text, task["answer_uci"])
            self.assertTrue(exercise.difficulty.startswith("Lichess puzzle"))
            board = Board(task["fen"])
            uci = task["answer_uci"]
            self.assertTrue(any(
                move.frm == parse_sq(uci[:2])
                and move.to == parse_sq(uci[2:4])
                and move.promotion == (uci[4].upper() if len(uci) == 5 else None)
                for move in board.legal_moves()
            ))

    def test_exact_original_advanced_bytes_and_license_are_required(self):
        original = advance.read_verified_source_snapshot
        with patch.object(advance, "read_verified_source_snapshot", side_effect=
                          lambda path, record: b'{"fake":1}'
                          if Path(path).suffix == ".json" else original(path, record)):
            with self.assertRaises((LawfulCorpusError, ValueError, KeyError)):
                advance.build_advanced_training()

    def test_truncated_rating_identity_rejected(self):
        original = advance.read_verified_source_snapshot
        def fake_advanced(path, record):
            raw = original(path, record)
            if Path(path).name.startswith("lichess_cc0_advanced_puzzles"):
                body = json.loads(raw)
                body["puzzles"][0]["rating"] = 1000
                return json.dumps(body).encode("utf-8")
            return raw
        with patch.object(advance, "read_verified_source_snapshot", fake_advanced):
            with self.assertRaises(LawfulCorpusError):
                advance.build_advanced_training()


if __name__ == "__main__":
    unittest.main()
