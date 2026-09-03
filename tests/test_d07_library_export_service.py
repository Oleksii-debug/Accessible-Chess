from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.game_identity import identity_for_game
from acs.library_export_service import (
    LibraryExportError,
    LibraryExportRequest,
    LibraryExportScope,
    LibraryExportService,
)
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService


PGN = '''[Event "Київ Open"]
[Site "Kyiv UKR"]
[Date "2026.08.31"]
[Round "1"]
[White "Ірина"]
[Black "Alpha"]
[Result "1-0"]
[ECO "C20"]
[Opening "King's Pawn Game"]

1. e4 $1 {центр} e5 (1... c5 $5 {Sicilian}) 2. Nf3 Nc6 1-0

[Event "Filtered Cup"]
[Site "Uzhhorod UKR"]
[Date "2026.08.31"]
[Round "2"]
[White "Beta"]
[Black "Gamma"]
[Result "*"]
[ECO "A00"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/6k1 w - - 0 1"]

1. Kf3 *

[Event "Filtered Cup"]
[Site "Košice SVK"]
[Date "2026.08.31"]
[Round "3"]
[White "Delta"]
[Black "Éva"]
[Result "*"]
[ECO "B20"]

1. e4 c5 2. Nf3 d6 *
'''


def _record_digests(games: tuple[object, ...] | list[object]) -> tuple[str, ...]:
    return tuple(identity_for_game(game).record_digest for game in games)


class LibraryExportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        self.db.import_pgn_text(PGN, source_name="unicode-library.pgn")
        self.search = GameSearchService(self.db)
        self.service = LibraryExportService(self.db, search_service=self.search)
        self.ids = tuple(
            item.game_id for item in self.search.search(GameSearchQuery(limit=20)).items
        )
        self.assertEqual(len(self.ids), 3)

    def tearDown(self) -> None:
        self.db.close()

    def _library_rows(self) -> tuple[tuple[object, ...], ...]:
        return tuple(
            tuple(row)
            for row in self.db.conn.execute(
                "SELECT id, source_id, source_index, pgn_text FROM games ORDER BY id"
            ).fetchall()
        )

    def test_selected_request_rejects_paths_duplicates_bool_and_unknown_fields(self) -> None:
        with self.assertRaises(ValueError):
            LibraryExportRequest.from_payload(
                {"scope": "selected", "game_ids": [self.ids[0]], "path": "C:/private.pgn"}
            )
        with self.assertRaises(ValueError):
            LibraryExportRequest.selected([self.ids[0], self.ids[0]])
        with self.assertRaises(ValueError):
            LibraryExportRequest.selected([True])
        with self.assertRaises(ValueError):
            LibraryExportRequest.from_payload(
                {"scope": "filtered", "filters": {"destination": "/tmp/private.pgn"}}
            )

    def test_selected_export_is_deterministic_by_canonical_game_id_and_reopens_equivalent(self) -> None:
        request = LibraryExportRequest.selected([self.ids[2], self.ids[0]])
        self.assertEqual(request.scope, LibraryExportScope.SELECTED)
        self.assertEqual(request.game_ids, (self.ids[0], self.ids[2]))
        expected = self.service.resolve_games(request)
        before_rows = self._library_rows()
        self.assertEqual(tuple(game.source_index for game in expected), (0, 0))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "selected.pgn"
            result = self.service.export_to(destination, request)
            reopened = open_pgn(destination)

        self.assertEqual(result.game_count, 2)
        self.assertEqual(len(reopened.games), len(expected))
        self.assertEqual(_record_digests(reopened.games), _record_digests(expected))
        self.assertEqual(tuple(game.source_index for game in reopened.games), (0, 1))
        self.assertEqual(self._library_rows(), before_rows)
        self.assertIn("Ірина", reopened.games[0].tags["White"])
        self.assertEqual(reopened.games[0].line.moves[0].nags, ["$1"])
        self.assertTrue(reopened.games[0].line.moves[0].comments)
        self.assertEqual(len(reopened.games[0].line.moves[0].variations), 1)

    def test_single_game_export_uses_same_canonical_path(self) -> None:
        request = LibraryExportRequest.selected([self.ids[1]])
        expected = self.service.resolve_games(request)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "single.pgn"
            result = self.service.export_to(destination, request)
            reopened = open_pgn(destination)
        self.assertEqual(result.game_count, 1)
        self.assertEqual(reopened.games, expected)
        self.assertEqual(reopened.games[0].tags["SetUp"], "1")
        self.assertEqual(
            reopened.games[0].tags["FEN"],
            "8/8/8/8/8/8/4K3/6k1 w - - 0 1",
        )

    def test_filtered_export_pages_canonical_search_and_preserves_id_order(self) -> None:
        request = LibraryExportRequest.filtered(GameSearchQuery(event="filtered cup"))
        expected_ids = tuple(
            item.game_id
            for item in self.search.search(GameSearchQuery(event="filtered cup", limit=200)).items
        )
        expected_games = tuple(self.service._load_game(game_id) for game_id in expected_ids)
        resolved = self.service.resolve_games(request)
        self.assertEqual(resolved, expected_games)
        self.assertEqual(len(resolved), 2)

        payload = request.browser_payload()
        self.assertEqual(payload["scope"], "filtered")
        self.assertNotIn("limit", payload["filters"])
        self.assertNotIn("after_game_id", payload["filters"])

    def test_empty_filtered_result_fails_before_any_file_write(self) -> None:
        request = LibraryExportRequest.filtered(GameSearchQuery(event="does-not-exist"))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "empty.pgn"
            with self.assertRaises(LibraryExportError):
                self.service.export_to(destination, request)
            self.assertFalse(destination.exists())

    def test_writer_failure_does_not_mutate_library(self) -> None:
        before_rows = self._library_rows()
        before_changes = self.db.conn.total_changes
        request = LibraryExportRequest.selected([self.ids[0], self.ids[1]])

        with patch(
            "acs.library_export_service.save_pgn_atomic",
            side_effect=OSError("write failed at /private/path/library.pgn"),
        ):
            with self.assertRaises(OSError):
                self.service.export_to(Path("ignored.pgn"), request)

        after_rows = self._library_rows()
        self.assertEqual(after_rows, before_rows)
        self.assertEqual(self.db.conn.total_changes, before_changes)

    def test_export_refuses_to_share_an_existing_write_transaction(self) -> None:
        self.db.conn.execute("BEGIN")
        try:
            with self.assertRaisesRegex(LibraryExportError, "busy"):
                self.service.resolve_games(LibraryExportRequest.selected([self.ids[0]]))
        finally:
            self.db.conn.rollback()


if __name__ == "__main__":
    unittest.main()
