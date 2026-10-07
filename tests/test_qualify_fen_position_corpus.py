import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.qualify_fen_position_corpus import (
    FenCorpusQualificationError,
    qualify_pgn_position_corpus,
    qualify_pgn_position_corpus_file,
)


def _pgn(movetext: str, result: str = "1-0") -> str:
    return (
        '[Event "FEN qualification fixture"]\n'
        '[Site "?"]\n'
        '[Date "2026.10.07"]\n'
        '[Round "1"]\n'
        '[White "White"]\n'
        '[Black "Black"]\n'
        f'[Result "{result}"]\n'
        '\n'
        f'{movetext}\n'
    )


class FenPositionCorpusQualifierTests(unittest.TestCase):
    def test_legal_game_round_trips_every_projected_position(self):
        text = _pgn("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0")
        report = qualify_pgn_position_corpus(
            text,
            source_sha256="fixture",
            min_games=1,
            min_positions=7,
        )

        self.assertEqual(report.game_count, 1)
        self.assertEqual(report.legal_move_count, 6)
        self.assertEqual(report.position_count, 7)
        self.assertGreaterEqual(report.unique_fen_count, 7)
        self.assertGreater(report.white_to_move_count, 0)
        self.assertGreater(report.black_to_move_count, 0)
        self.assertGreater(report.castling_rights_count, 0)
        self.assertGreater(report.en_passant_count, 0)
        self.assertGreater(report.fullmove_gt_one_count, 0)

    def test_illegal_source_move_fails_closed_without_position_claim(self):
        text = _pgn("1. e4 e5 2. e5 1-0")
        with self.assertRaisesRegex(
            FenCorpusQualificationError,
            "complete legal projection",
        ):
            qualify_pgn_position_corpus(text)

    def test_edge_coverage_is_an_explicit_acceptance_floor(self):
        text = _pgn("1. e4 e5 2. Nf3 Nc6 1-0")
        with self.assertRaisesRegex(
            FenCorpusQualificationError,
            "castling_rights_cleared",
        ):
            qualify_pgn_position_corpus(
                text,
                min_games=1,
                min_positions=5,
                require_edge_coverage=True,
            )

    def test_file_qualification_delegates_to_canonical_source_snapshot(self):
        text = _pgn("1. d4 d5 2. c4 e6 1-0")
        payload = text.encode("utf-8")
        source = mock.Mock()
        source.sha256 = "canonical-source-digest"
        path = Path("must-not-be-opened-directly.pgn")

        with mock.patch(
            "tools.qualify_fen_position_corpus.read_source_snapshot",
            return_value=(source, payload),
        ) as reader:
            report = qualify_pgn_position_corpus_file(
                path,
                min_games=1,
                min_positions=5,
            )

        reader.assert_called_once_with(path, max_bytes=16 * 1024 * 1024)
        self.assertEqual(report.source_sha256, "canonical-source-digest")
        self.assertEqual(report.game_count, 1)
        self.assertEqual(report.position_count, 5)

    def test_file_qualification_binds_report_to_exact_source_bytes(self):
        text = _pgn("1. d4 d5 2. c4 e6 1-0")
        payload = text.encode("utf-8")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "corpus.pgn"
            path.write_bytes(payload)
            report = qualify_pgn_position_corpus_file(
                path,
                min_games=1,
                min_positions=5,
            )

        self.assertEqual(report.source_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(report.game_count, 1)
        self.assertEqual(report.position_count, 5)


if __name__ == "__main__":
    unittest.main()
