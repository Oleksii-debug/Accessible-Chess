from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import open_pgn


# Minimal strict equivalent of the real Lichess PGN-05 record #201 surface.
# The real legal record and its pinned SHA remain external acceptance evidence;
# this fixture exists only to make the proven regression deterministic.
ATTACHED_SYMBOLIC_NAG_PGN = '''[Event "PGN-05 attached NAG regression"]
[Site "?"]
[Date "2026.08.28"]
[Round "?"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. d3 Bc5 5. O-O d6 6. c3 O-O 7. Re1 a6 8. Bb3 Ba7 9. Nbd2 Re8 10. Nf1 h6 11. c4?! *
'''


class D06FileIngressNagNormalizationTests(unittest.TestCase):
    def test_file_and_document_ingress_match_canonical_strict_symbolic_nag_normalization(self) -> None:
        canonical = parse_pgn_text(ATTACHED_SYMBOLIC_NAG_PGN, strict=True)
        self.assertEqual(len(canonical), 1)
        expected = canonical[0]
        self.assertEqual(expected.line.moves[-1].san, "c4")
        self.assertEqual(expected.line.moves[-1].nags, ["?!"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attached-nag.pgn"
            path.write_text(ATTACHED_SYMBOLIC_NAG_PGN, encoding="utf-8", newline="\n")

            opened = open_pgn(path)
            self.assertEqual(opened.games, canonical)
            self.assertEqual(opened.games[0].line.moves[-1].san, "c4")
            self.assertEqual(opened.games[0].line.moves[-1].nags, ["?!"])

            session = PgnDocumentSession.open(path)
            self.assertEqual(session.workspace.games(), canonical)
            self.assertEqual(session.view().game_count, 1)
            self.assertFalse(session.view().global_warnings)
            self.assertTrue(session.view().source_overwrite_safe)


if __name__ == "__main__":
    unittest.main()
