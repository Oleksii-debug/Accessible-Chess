from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
)


class D07AcsdbCanonicalPgnIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()

    def tearDown(self) -> None:
        self.db.close()

    def test_external_import_cannot_bypass_canonical_d06_tag_size_bound(self) -> None:
        oversized = "X" * (MAX_PGN_TAG_VALUE_CHARS + 1)
        text = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'

        with self.assertRaises(PgnRoundTripError) as caught:
            self.db.import_pgn_text(text, "oversized-event.pgn")

        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        failures = self.db.list_import_attempts(status="failed")
        self.assertEqual(len(failures), 1)
        self.assertIsNone(failures[0]["source_id"])
        self.assertEqual(failures[0]["error_message"], "PgnRoundTripError: import failed")
        self.assertNotIn(oversized[:32], failures[0]["error_message"])

    def test_canonical_recovery_mode_preserves_damaged_warning_import_contract(self) -> None:
        text = '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5\n'
        canonical = parse_pgn_text(text, strict=False)
        self.assertEqual(len(canonical), 1)
        self.assertTrue(canonical[0].warnings)

        report = self.db.import_pgn_text(text, "damaged-recovery.pgn")

        self.assertEqual(report.total, 1)
        self.assertEqual(report.warning, 1)
        self.assertEqual(report.full, 0)
        self.assertEqual(report.damaged, 0)
        attempt = self.db.get_import_attempt(report.attempt_id)
        self.assertEqual(attempt["status"], "warning")
        self.assertEqual(attempt["game_count"], 1)
        self.assertEqual(attempt["warning_count"], 1)
        self.assertIsNone(attempt["error_message"])
        stored = self.db.get_game(report.game_ids[0])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["import_status"], "warning")


if __name__ == "__main__":
    unittest.main()
