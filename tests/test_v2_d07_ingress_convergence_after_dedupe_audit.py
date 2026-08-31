from __future__ import annotations

import hashlib
import unittest

from acs.acsdb import AcsDatabase
from acs.duplicate_detection import detect_pgn_duplicates
from acs.library_import_service import LibraryImportService
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)


_ATTACHED_NAG = '[Event "NAG equivalence"]\n[Result "*"]\n\n1. e4?! *\n'


class V2D07IngressConvergenceAfterDedupeAuditTests(unittest.TestCase):
    def test_public_acsdb_import_respects_canonical_d06_tag_bound(self) -> None:
        oversized = "X" * (MAX_PGN_TAG_VALUE_CHARS + 1)
        text = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'

        with self.assertRaises(PgnRoundTripError) as canonical:
            parse_pgn_text(text, strict=True)
        self.assertEqual(canonical.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)

        with AcsDatabase() as database:
            with self.assertRaises(PgnRoundTripError) as consumer:
                database.import_pgn_text(text, "oversized-event.pgn")
            self.assertEqual(consumer.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)
            self.assertEqual(
                int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
                0,
            )
            self.assertEqual(
                int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                0,
            )

    def test_dedupe_uses_canonical_record_identity_for_attached_symbolic_nag(self) -> None:
        canonical_games = parse_pgn_text(_ATTACHED_NAG, strict=True)
        canonical_text = serialize_pgn_text(canonical_games)
        digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()

        with AcsDatabase() as database:
            imported = LibraryImportService(database).import_games(
                canonical_games,
                source_name="canonical.pgn",
                source_format="pgn",
                source_sha256=digest,
                source_warning_count=0,
            )
            self.assertEqual(imported.game_count, 1)

            report = detect_pgn_duplicates(database, _ATTACHED_NAG)
            kinds = {match.kind for match in report.matches}

        self.assertTrue(
            kinds.intersection({"record", "tree"}),
            f"canonical-equivalent PGN was degraded to non-semantic duplicate kinds: {sorted(kinds)}",
        )


if __name__ == "__main__":
    unittest.main()
