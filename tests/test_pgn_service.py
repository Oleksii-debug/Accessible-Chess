import tempfile
from pathlib import Path
import unittest

from acs.gametree import parse_games, serialize_games
from acs.import_contract import ImportQuality
from acs.pgn_service import (
    PgnConcurrentWriteError,
    PgnFileImporter,
    export_game_atomic,
    open_pgn,
    save_pgn_atomic,
)


RICH_PGN = '''[Event "Main"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 {main comment} e5 $1 (1... c5 {Sicilian} 2. Nf3) 2. Nf3 Nc6 1-0

[Event "Second"]
[Result "*"]

1. d4 d5 2. c4 *
'''


class PgnFileServiceTests(unittest.TestCase):
    def test_open_preserves_multi_game_recursive_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rich.pgn"
            path.write_text(RICH_PGN, encoding="utf-8")
            opened = open_pgn(path)

            self.assertEqual(opened.total_games, 2)
            self.assertEqual(opened.games[0].tags["Event"], "Main")
            first = opened.games[0].line.moves[0]
            self.assertEqual(first.san, "e4")
            second = opened.games[0].line.moves[1]
            self.assertEqual(second.san, "e5")
            self.assertIn("$1", second.nags)
            self.assertEqual(len(second.variations), 1)
            self.assertEqual(second.variations[0].moves[0].san, "c5")
            self.assertEqual(second.variations[0].moves[1].san, "Nf3")

    def test_atomic_save_round_trips_rich_structure(self):
        games = parse_games(RICH_PGN)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.pgn"
            saved = save_pgn_atomic(path, games)
            self.assertTrue(path.exists())
            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)

            reopened = open_pgn(path)
            normalized_original = serialize_games(games)
            normalized_reopened = serialize_games(reopened.games)
            self.assertEqual(normalized_reopened, normalized_original)

    def test_existing_file_is_protected_by_default(self):
        games = parse_games('[Event "A"]\n[Result "*"]\n\n1. e4 *')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.pgn"
            path.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                save_pgn_atomic(path, games)
            self.assertEqual(path.read_text(encoding="utf-8"), "do not replace")

    def test_expected_hash_prevents_lost_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edit.pgn"
            path.write_text('[Event "A"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            path.write_text('[Event "Other editor"]\n[Result "*"]\n\n1. d4 *\n', encoding="utf-8")

            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(
                    path,
                    opened.games,
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )
            self.assertIn("Other editor", path.read_text(encoding="utf-8"))

    def test_overwrite_with_matching_hash_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edit.pgn"
            path.write_text('[Event "A"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            opened.games[0].tags["Event"] = "Changed safely"
            save_pgn_atomic(
                path,
                opened.games,
                overwrite=True,
                expected_sha256=opened.source.sha256,
            )
            self.assertIn("Changed safely", path.read_text(encoding="utf-8"))

    def test_read_only_importer_reports_each_game_and_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warning.pgn"
            path.write_text(
                '[Event "Mismatch"]\n[Result "1-0"]\n\n1. e4 0-1\n',
                encoding="utf-8",
            )
            report = PgnFileImporter().inspect(path)
            self.assertEqual(report.total, 1)
            self.assertEqual(report.records[0].quality, ImportQuality.WARNING)
            self.assertTrue(report.records[0].warnings)
            self.assertEqual(report.source.sha256, open_pgn(path).source.sha256)

    def test_blank_pgn_is_explicitly_damaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.pgn"
            path.write_text("", encoding="utf-8")
            report = PgnFileImporter().inspect(path)
            self.assertEqual(report.total, 1)
            self.assertEqual(report.records[0].quality, ImportQuality.DAMAGED)

    def test_single_game_export_uses_same_atomic_path(self):
        game = parse_games('[Event "One"]\n[Result "*"]\n\n1. Nf3 *')[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.pgn"
            exported = export_game_atomic(path, game)
            self.assertEqual(exported.sha256, open_pgn(path).source.sha256)
            self.assertEqual(open_pgn(path).total_games, 1)


if __name__ == "__main__":
    unittest.main()
