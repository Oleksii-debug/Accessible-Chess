from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.game_identity import identity_for_game
import acs.library_pgn_export as library_export
from acs.library_pgn_export import (
    LibraryPgnExportError,
    LibraryPgnExportErrorCode,
    LibraryPgnExportService,
)
from acs.pgn_service import PgnConcurrentWriteError, open_pgn


_LIBRARY_PGN = """[Event "Партія один"]
[Site "Uzhhorod"]
[Date "2026.08.31"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 (2. Bc4 Nf6) Nc6 1-0

[Event "Partie deux ♞"]
[Site "Nitra"]
[Date "2026.08.31"]
[Round "2"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
"""


class LibraryPgnExportServiceTests(unittest.TestCase):
    def _database(self):
        database = AcsDatabase()
        report = database.import_pgn_text(_LIBRARY_PGN, source_name="real-library.pgn")
        self.assertEqual(len(report.game_ids), 2)
        return database, tuple(report.game_ids)

    def test_subset_exports_in_requested_order_and_reopens_semantically(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        service = LibraryPgnExportService(database)

        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "вибірка ♞.pgn"
            result = service.export_subset((game_ids[1], game_ids[0]), destination)
            reopened = open_pgn(destination)

            self.assertEqual(result.game_count, 2)
            self.assertEqual(reopened.total_games, 2)
            self.assertEqual(
                [game.tags["Event"] for game in reopened.games],
                ["Partie deux ♞", "Партія один"],
            )
            expected_records = []
            for game_id in (game_ids[1], game_ids[0]):
                stored = database.get_game(game_id)
                self.assertIsNotNone(stored)
                parsed = library_export.parse_pgn_text(stored["pgn_text"], strict=True)
                self.assertEqual(len(parsed), 1)
                expected_records.append(identity_for_game(parsed[0]).record_digest)
            self.assertEqual(
                [identity_for_game(game).record_digest for game in reopened.games],
                expected_records,
            )
            self.assertEqual(destination.read_bytes().decode("utf-8").count("\r"), 0)

    def test_late_missing_library_game_preserves_existing_destination_and_cleans_temp(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        service = LibraryPgnExportService(database)

        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"existing library export\n"
            destination.write_bytes(original)

            with self.assertRaises(LibraryPgnExportError) as caught:
                service.export_subset((game_ids[0], 999_999_999), destination)

            self.assertEqual(caught.exception.code, LibraryPgnExportErrorCode.GAME_NOT_FOUND)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])

    def test_stale_destination_fingerprint_detects_external_change_before_publish(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        service = LibraryPgnExportService(database)
        real_save = library_export.save_pgn_atomic

        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "existing.pgn"
            destination.write_bytes(b"first version\n")
            external = b"external newer version\n"

            def racing_save(path, games, *, overwrite=False, expected_sha256=None):
                Path(path).write_bytes(external)
                return real_save(
                    path,
                    games,
                    overwrite=overwrite,
                    expected_sha256=expected_sha256,
                )

            with patch("acs.library_pgn_export.save_pgn_atomic", side_effect=racing_save):
                with self.assertRaises(PgnConcurrentWriteError):
                    service.export_subset((game_ids[0],), destination)

            self.assertEqual(destination.read_bytes(), external)

    def test_invalid_stored_pgn_fails_closed_without_partial_publication(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        database.conn.execute(
            "UPDATE games SET pgn_text=? WHERE id=?",
            ('[Event "Broken"]\n[Result "*"]\n\n1. e4 {unterminated *', game_ids[1]),
        )
        database.conn.commit()
        service = LibraryPgnExportService(database)

        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"keep me\n"
            destination.write_bytes(original)

            with self.assertRaises(LibraryPgnExportError) as caught:
                service.export_subset(game_ids, destination)

            self.assertEqual(
                caught.exception.code,
                LibraryPgnExportErrorCode.INVALID_STORED_PGN,
            )
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])

    def test_selection_validation_is_exact_and_duplicate_safe(self) -> None:
        database, game_ids = self._database()
        self.addCleanup(database.close)
        service = LibraryPgnExportService(database)
        with tempfile.TemporaryDirectory() as raw_dir:
            destination = Path(raw_dir) / "unused.pgn"
            for bad in ([], (), (True,), (game_ids[0], game_ids[0])):
                with self.subTest(bad=bad):
                    with self.assertRaises(LibraryPgnExportError) as caught:
                        service.export_subset(bad, destination)
                    self.assertEqual(
                        caught.exception.code,
                        LibraryPgnExportErrorCode.INVALID_SELECTION,
                    )
                    self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
