from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportProgress, LibraryImportService
from acs.pgn_roundtrip import canonical_round_trip_text, parse_pgn_text
from acs.pgn_service import PgnConcurrentWriteError, open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


RICH_PGN = '''[Event "Київ Integration"]
[Site "Kyiv UKR"]
[Date "2026.08.24"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 {Main plan} e5 (1... c5 $1 {Sicilian branch}) 2. Nf3 Nc6 *
'''

EXTERNAL_PGN = '[Event "External writer"]\n[Result "*"]\n\n1. d4 *\n'


class WholeProductUserJourneyTests(unittest.TestCase):
    def test_pgn_save_library_search_reopen_and_stale_write_rejection(self):
        canonical = canonical_round_trip_text(RICH_PGN)
        self.assertEqual(len(canonical.games), 1)
        self.assertEqual(canonical.games[0].line.moves[0].comments_after[0].text, "Main plan")
        self.assertEqual(
            canonical.games[0].line.moves[1].variations[0].moves[0].comments_after[0].text,
            "Sicilian branch",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pgn_path = root / "lesson.pgn"
            database_path = root / "library.acsdb"

            saved = save_pgn_atomic(pgn_path, canonical.games)
            opened = open_pgn(pgn_path)
            self.assertEqual(saved.sha256, opened.source.sha256)
            self.assertEqual(canonical_round_trip_text(pgn_path.read_text(encoding="utf-8")).text, canonical.text)

            database = AcsDatabase(database_path)
            try:
                progress: list[LibraryImportProgress] = []
                imported = LibraryImportService(database).import_games(
                    opened.games,
                    source_name=pgn_path.name,
                    source_format="PGN",
                    source_sha256=opened.source.sha256,
                    progress_callback=progress.append,
                )
                self.assertEqual(imported.game_count, 1)
                self.assertEqual(
                    [(item.processed_games, item.total_games) for item in progress],
                    [(0, 1), (1, 1)],
                )

                page = GameSearchService(database).search(
                    GameSearchQuery(event="київ", player="alpha", source_name="lesson")
                )
                self.assertEqual(len(page.items), 1)
                row = database.get_game(page.items[0].game_id)
                self.assertIsNotNone(row)
                reopened = parse_pgn_text(row["pgn_text"])
                self.assertEqual(reopened[0].tags["Event"], "Київ Integration")
                self.assertEqual(
                    reopened[0].line.moves[1].variations[0].moves[0].comments_after[0].text,
                    "Sicilian branch",
                )
            finally:
                database.close()

            # The earlier fingerprint cannot overwrite a later external edit.
            pgn_path.write_text(EXTERNAL_PGN, encoding="utf-8")
            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(
                    pgn_path,
                    canonical.games,
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )
            self.assertEqual(pgn_path.read_text(encoding="utf-8"), EXTERNAL_PGN)
            self.assertEqual(list(root.glob("lesson.pgn.*.tmp")), [])
            self.assertEqual(list(root.glob("lesson.pgn.cas-*.bak")), [])


if __name__ == "__main__":
    unittest.main()
