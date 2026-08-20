import tempfile
from pathlib import Path
import unittest

from acs.gametree import (
    GameTreeErrorCode,
    GameTreeSerializationError,
    parse_games,
    serialize_games,
)
from acs.import_contract import ImportQuality
from acs.pgn_service import (
    PgnConcurrentWriteError,
    PgnFileImporter,
    _save_lock_path,
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

    def test_atomic_save_preserves_semicolon_brace_and_result_mismatch_evidence(self):
        game = parse_games(
            '[Event "Damaged source"]\n'
            '[Result "1-0"]\n\n'
            '1. e4 ;literal } brace\n'
            ' e5 0-1\n'
        )[0]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loss-aware.pgn"
            save_pgn_atomic(path, (game,))
            reopened = open_pgn(path).games[0]

        comment = reopened.line.moves[0].comments_after[0]
        self.assertEqual(comment.text, "literal } brace")
        self.assertEqual(comment.style, "semicolon")
        self.assertEqual(reopened.tags["Result"], "1-0")
        self.assertEqual(reopened.line.result, "0-1")
        self.assertTrue(any("differs" in warning for warning in reopened.warnings))

    def test_quarantined_nested_rav_is_damaged_and_atomic_export_fails_closed(self):
        source = (
            '[Event "Damaged"]\n[Result "*"]\n\n'
            '1. e4 (1. d4 * 1... d5) e5 *\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "damaged.pgn"
            destination = Path(tmp) / "must-not-exist.pgn"
            source_path.write_text(source, encoding="utf-8")

            opened = open_pgn(source_path)
            self.assertEqual(len(opened.games[0].recovery_issues), 1)
            report = PgnFileImporter().inspect(source_path)
            self.assertEqual(report.records[0].quality, ImportQuality.DAMAGED)
            self.assertIn("explicit repair", report.records[0].message)

            with self.assertRaises(GameTreeSerializationError) as blocked:
                export_game_atomic(destination, opened.games[0])

            self.assertEqual(blocked.exception.code, GameTreeErrorCode.UNRESOLVED_RECOVERY)
            self.assertFalse(destination.exists())
            self.assertFalse(_save_lock_path(destination).exists())
            self.assertEqual(list(Path(tmp).glob("must-not-exist.pgn.*.tmp")), [])

    def test_import_inspection_isolates_damaged_and_full_games(self):
        collection = (
            '[Event "Damaged"]\n[Result "*"]\n\n'
            '$1 1. e4 *\n\n'
            '[Event "Clean"]\n[Result "*"]\n\n'
            '1. d4 d5 *\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.pgn"
            path.write_text(collection, encoding="utf-8")
            report = PgnFileImporter().inspect(path)

        self.assertEqual([record.source_record_id for record in report.records], ["0", "1"])
        self.assertEqual(
            [record.quality for record in report.records],
            [ImportQuality.DAMAGED, ImportQuality.FULL],
        )
        self.assertTrue(any("orphan annotation" in warning for warning in report.records[0].warnings))
        self.assertEqual(report.records[1].warnings, ())

    def test_tag_damage_is_bounded_per_game_during_import_inspection(self):
        collection = (
            r'[Event "unsupported \q escape"]' "\n"
            '[Result "*"]\n\n'
            '1. e4 *\n\n'
            '[Event "unterminated]\n'
            '[Result "*"]\n\n'
            '1. d4 *\n\n'
            '[Event "Clean"]\n'
            '[Result "*"]\n\n'
            '1. c4 *\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tag-damage.pgn"
            path.write_text(collection, encoding="utf-8")
            report = PgnFileImporter().inspect(path)

        self.assertEqual(
            [record.source_record_id for record in report.records],
            ["0", "1", "2"],
        )
        self.assertEqual(
            [record.quality for record in report.records],
            [ImportQuality.DAMAGED, ImportQuality.DAMAGED, ImportQuality.FULL],
        )
        self.assertTrue(
            any("unsupported escape" in warning for warning in report.records[0].warnings)
        )
        self.assertTrue(
            any("malformed tag line" in warning for warning in report.records[1].warnings)
        )
        self.assertEqual(report.records[2].warnings, ())


if __name__ == "__main__":
    unittest.main()
