from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.gametree import parse_games, serialize_games
from acs.import_contract import ImportQuality
from acs.pgn_service import PgnFileImporter


_WARNING_PREFIX = "missing movetext game termination marker"


class Dev2PgnTerminationSemanticsTests(unittest.TestCase):
    def test_truncated_root_movetext_is_recoverable_but_explicitly_loss_aware(self) -> None:
        game = parse_games(
            '[Event "Truncated"]\n[White "Alpha"]\n[Black "Beta"]\n\n'
            '1. e4 e5 2. Nf3'
        )[0]

        self.assertEqual(game.line.result, "*")
        self.assertEqual(game.tags["Result"], "*")
        self.assertTrue(any(warning.startswith(_WARNING_PREFIX) for warning in game.warnings))

        normalized = serialize_games((game,))
        self.assertTrue(normalized.rstrip().endswith("*"))
        reparsed = parse_games(normalized)[0]
        self.assertFalse(any(warning.startswith(_WARNING_PREFIX) for warning in reparsed.warnings))

    def test_valid_header_result_can_recover_effective_result_but_not_hide_missing_marker(self) -> None:
        game = parse_games('[Event "Recovered"]\n[Result "1-0"]\n\n1. e4 e5')[0]

        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.line.result, "1-0")
        self.assertTrue(any(warning.startswith(_WARNING_PREFIX) for warning in game.warnings))

    def test_explicit_termination_marker_does_not_emit_recovery_warning(self) -> None:
        game = parse_games('[Event "Complete"]\n[Result "*"]\n\n1. e4 e5 *')[0]

        self.assertEqual(game.line.result, "*")
        self.assertFalse(any(warning.startswith(_WARNING_PREFIX) for warning in game.warnings))

    def test_missing_marker_isolated_to_affected_game_in_multi_game_source(self) -> None:
        games = parse_games(
            '[Event "Truncated"]\n[Result "*"]\n\n1. e4 e5\n\n'
            '[Event "Complete"]\n[Result "0-1"]\n\n1. d4 d5 0-1'
        )

        self.assertEqual(len(games), 2)
        self.assertTrue(any(warning.startswith(_WARNING_PREFIX) for warning in games[0].warnings))
        self.assertFalse(any(warning.startswith(_WARNING_PREFIX) for warning in games[1].warnings))
        self.assertEqual(games[1].line.result, "0-1")

    def test_file_importer_never_false_greens_missing_marker_as_full(self) -> None:
        text = (
            '[Event "Truncated"]\n'
            '[White "Alpha"]\n'
            '[Black "Beta"]\n\n'
            '1. e4 e5 2. Nf3'
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "truncated.pgn"
            source.write_text(text, encoding="utf-8")
            report = PgnFileImporter().inspect(source)

        self.assertEqual(report.total, 1)
        self.assertEqual(report.records[0].quality, ImportQuality.WARNING)
        self.assertEqual(report.counts[ImportQuality.FULL.value], 0)
        self.assertTrue(
            any(warning.startswith(_WARNING_PREFIX) for warning in report.records[0].warnings)
        )


if __name__ == "__main__":
    unittest.main()
