from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.duplicate_detection import detect_pgn_duplicates
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
)


class CurrentD07CanonicalIngressTests(unittest.TestCase):
    def test_library_import_enforces_canonical_tag_bound_before_publication(self) -> None:
        oversized = "X" * (MAX_PGN_TAG_VALUE_CHARS + 1)
        text = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'

        with AcsDatabase() as database:
            with self.assertRaises(PgnRoundTripError) as raised:
                database.import_pgn_text(text, "oversized-event.pgn")

            self.assertEqual(raised.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                0,
            )
            self.assertEqual(
                database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                0,
            )
            failures = database.list_import_attempts(status="failed")
            self.assertEqual(len(failures), 1)
            self.assertIsNone(failures[0]["source_id"])
            self.assertEqual(
                failures[0]["error_message"],
                "PgnRoundTripError: import failed",
            )

    def test_attached_symbolic_nag_uses_canonical_record_identity(self) -> None:
        attached = '''[Event "NAG equivalence"]
[Result "*"]

1. e4?! *
'''
        with AcsDatabase() as database:
            imported = database.import_pgn_text(attached, "attached.pgn")
            stored = database.get_game(imported.game_ids[0])
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertIn("e4 ?!", stored["pgn_text"])

            report = detect_pgn_duplicates(database, attached)
            semantic = [
                match for match in report.matches if match.kind in {"record", "tree"}
            ]
            self.assertEqual(len(semantic), 1)
            self.assertEqual(semantic[0].kind, "record")
            self.assertEqual(semantic[0].existing_game_id, imported.game_ids[0])


if __name__ == "__main__":
    unittest.main()
