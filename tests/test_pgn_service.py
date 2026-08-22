import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from acs.gametree import parse_games, serialize_games
from acs.import_contract import ImportQuality
from acs.pgn_service import PgnConcurrentWriteError, PgnFileImporter, export_game_atomic, open_pgn, save_pgn_atomic


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
            second = opened.games[0].line.moves[1]
            self.assertEqual(second.san, "e5")
            self.assertIn("$1", second.nags)
            self.assertEqual(len(second.variations), 1)
            self.assertEqual([m.san for m in second.variations[0].moves], ["c5", "Nf3"])

    def test_atomic_save_round_trips_rich_structure(self):
        games = parse_games(RICH_PGN)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.pgn"
            saved = save_pgn_atomic(path, games)
            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)
            self.assertEqual(serialize_games(open_pgn(path).games), serialize_games(games))

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
                save_pgn_atomic(path, opened.games, overwrite=True, expected_sha256=opened.source.sha256)
            self.assertIn("Other editor", path.read_text(encoding="utf-8"))

    def test_expected_hash_preserves_writer_racing_at_replace_boundary(self):
        games = parse_games('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.pgn"
            path.write_text('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n', encoding="utf-8")
            opened = open_pgn(path)
            real_replace = os.replace

            def racing_replace(src, dst):
                Path(dst).write_text(
                    '[Event "Concurrent writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_replace(src, dst)

            with mock.patch("acs.pgn_service.os.replace", side_effect=racing_replace):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        path,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )
            self.assertIn("Concurrent writer", path.read_text(encoding="utf-8"))

    def test_no_overwrite_publication_is_atomic_no_clobber(self):
        games = parse_games('[Event "Our export"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new-shared.pgn"
            real_link = os.link

            def racing_link(src, dst, *args, **kwargs):
                Path(dst).write_text(
                    '[Event "Created by another writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_link(src, dst, *args, **kwargs)

            with mock.patch("acs.pgn_service.os.link", side_effect=racing_link):
                with self.assertRaises(FileExistsError):
                    save_pgn_atomic(path, games, overwrite=False)
            self.assertIn("Created by another writer", path.read_text(encoding="utf-8"))

    def test_importer_reports_warning_and_blank_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            warning = Path(tmp) / "warning.pgn"
            warning.write_text('[Event "Mismatch"]\n[Result "1-0"]\n\n1. e4 0-1\n', encoding="utf-8")
            report = PgnFileImporter().inspect(warning)
            self.assertEqual(report.records[0].quality, ImportQuality.WARNING)
            blank = Path(tmp) / "blank.pgn"
            blank.write_text("", encoding="utf-8")
            self.assertEqual(PgnFileImporter().inspect(blank).records[0].quality, ImportQuality.DAMAGED)

    def test_single_game_export_uses_atomic_path(self):
        game = parse_games('[Event "One"]\n[Result "*"]\n\n1. Nf3 *')[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.pgn"
            exported = export_game_atomic(path, game)
            self.assertEqual(exported.sha256, open_pgn(path).source.sha256)
            self.assertEqual(open_pgn(path).total_games, 1)


if __name__ == "__main__":
    unittest.main()
