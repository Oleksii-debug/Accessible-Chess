from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.chesscore import Board
from acs.position_editor import PositionState, PositionValidationError


CORPUS = Path(__file__).resolve().parent / "data" / "fen_edge_corpus_v1.json"


class FenEdgeCorpusTests(unittest.TestCase):
    def test_project_authored_corpus_declares_non_external_provenance(self):
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        provenance = payload["provenance"]
        self.assertEqual(provenance["kind"], "project-authored-deterministic-test-data")
        self.assertIs(provenance["external_bytes"], False)
        self.assertGreaterEqual(len(payload["records"]), 18)

    def test_representation_and_canonical_playability_boundaries(self):
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        for record in payload["records"]:
            fen = record["fen"]
            with self.subTest(record=record["id"], boundary="representation"):
                try:
                    state = PositionState.from_fen(fen)
                except (PositionValidationError, ValueError):
                    representation_valid = False
                    state = None
                else:
                    representation_valid = True
                self.assertEqual(representation_valid, record["representation_valid"])
                if state is not None:
                    self.assertEqual(PositionState.from_fen(state.to_fen()), state)

            with self.subTest(record=record["id"], boundary="canonical-board"):
                try:
                    board = Board(fen)
                except ValueError:
                    playable = False
                    board = None
                else:
                    playable = True
                self.assertEqual(playable, record["playable"])
                if board is not None:
                    self.assertEqual(board.fen(), record["canonical"])
                    self.assertEqual(Board(board.fen()).fen(), record["canonical"])


if __name__ == "__main__":
    unittest.main()
