from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile
import unittest

from acs.legacy_library_migration import LegacyLibraryMigrationError, migrate_legacy_library
from acs.pgn_roundtrip import PgnRoundTripError, PgnRoundTripErrorCode, parse_pgn_text


MALFORMED_SAN_PGN = '''[Event "Legacy malformed SAN"]
[Site "?"]
[Date "2026.08.31"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. NotAMove *
'''

VALID_PGN = '''[Event "Legacy valid"]
[Site "?"]
[Date "2026.08.31"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
'''


class V2AuditBLegacySchema0CanonicalIngressTests(unittest.TestCase):
    def _legacy_db(self, root: Path, pgn: str) -> Path:
        path = root / "legacy-library.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO games(id, title, pgn, created_at) VALUES(?,?,?,?)",
                (1, "legacy-source.pgn", pgn, "2026-08-31T00:00:00Z"),
            )
            connection.commit()
        finally:
            connection.close()
        return path

    def test_canonical_d06_rejects_the_malformed_san_fixture(self) -> None:
        with self.assertRaises(PgnRoundTripError) as caught:
            parse_pgn_text(MALFORMED_SAN_PGN, strict=False)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.INVALID_SAN)

    def test_schema0_conversion_must_not_publish_pgn_rejected_by_canonical_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._legacy_db(root, MALFORMED_SAN_PGN)
            destination = root / "library.acsdb"

            with self.assertRaises(LegacyLibraryMigrationError):
                migrate_legacy_library(source, destination)

            self.assertFalse(destination.exists())
            self.assertTrue(source.exists())
            with sqlite3.connect(source) as connection:
                self.assertEqual(
                    connection.execute("SELECT pgn FROM games WHERE id=1").fetchone()[0],
                    MALFORMED_SAN_PGN,
                )

    def test_valid_exact_legacy_schema_still_converts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._legacy_db(root, VALID_PGN)
            destination = root / "library.acsdb"

            result = migrate_legacy_library(source, destination)
            self.assertEqual(result.legacy_rows, 1)
            self.assertEqual(result.games, 1)
            self.assertTrue(destination.is_file())
            self.assertTrue(source.is_file())


if __name__ == "__main__":
    unittest.main()
