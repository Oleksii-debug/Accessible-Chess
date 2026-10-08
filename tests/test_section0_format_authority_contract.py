from __future__ import annotations

import unittest
from unittest import mock

import acs.chesscore as chesscore
import acs.epd as epd
import acs.game_identity as game_identity
import acs.gametree as gametree
import acs.library_import_service as library_import_service
import acs.pgn_roundtrip as pgn_roundtrip
import acs.position_editor as position_editor


_START_EPD = (
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR "
    "w KQkq -"
)
_GAME = '[Event "Authority"]\n[Result "*"]\n\n1. e4 *\n'


class Section0FormatAuthorityContractTests(unittest.TestCase):
    def test_format_modules_reuse_exact_canonical_data_types(self) -> None:
        self.assertIs(epd.PositionState, position_editor.PositionState)
        self.assertIs(pgn_roundtrip.PgnGame, gametree.PgnGame)
        self.assertIs(pgn_roundtrip.MoveNode, gametree.MoveNode)
        self.assertIs(pgn_roundtrip.VariationLine, gametree.VariationLine)
        self.assertIs(pgn_roundtrip.parse_games, gametree.parse_games)
        self.assertIs(pgn_roundtrip.serialize_games, gametree.serialize_games)
        self.assertIs(library_import_service.PgnGame, gametree.PgnGame)
        self.assertIs(game_identity.PgnGame, gametree.PgnGame)

    def test_epd_delegates_position_construction_to_canonical_position_state(self) -> None:
        canonical_from_fen = position_editor.PositionState.from_fen
        calls: list[str] = []

        def checked_from_fen(fen: str) -> position_editor.PositionState:
            calls.append(fen)
            return canonical_from_fen(fen)

        with mock.patch.object(
            epd.PositionState,
            "from_fen",
            side_effect=checked_from_fen,
        ):
            record = epd.parse_epd(_START_EPD)

        self.assertEqual(calls, [_START_EPD + " 0 1"])
        self.assertIs(type(record.position), position_editor.PositionState)
        self.assertEqual(record.position.to_fen(), _START_EPD + " 0 1")

    def test_playable_move_and_san_authority_is_chesscore(self) -> None:
        board = chesscore.Board()
        move = board.parse_move("e4")
        self.assertIs(type(move), chesscore.Move)
        self.assertEqual(board.san(move), "e4")

        before = board.fen()
        self.assertEqual(board.push(move), "e4")
        self.assertNotEqual(board.fen(), before)
        self.assertEqual(board.turn, "b")

    def test_source_index_does_not_change_canonical_game_identity(self) -> None:
        game = gametree.parse_games(_GAME)[0]
        first = game_identity.identity_for_game(game)

        game.source_index = 991
        second = game_identity.identity_for_game(game)

        self.assertEqual(first.schema_version, second.schema_version)
        self.assertEqual(first.tree_digest, second.tree_digest)
        self.assertEqual(first.record_digest, second.record_digest)

    def test_strict_pgn_rejects_malformed_header_without_publishing_game(self) -> None:
        malformed = '[Event "Broken]\n[Result "*"]\n\n1. e4 *\n'
        with self.assertRaises(pgn_roundtrip.PgnRoundTripError) as caught:
            pgn_roundtrip.parse_pgn_text(malformed, strict=True)

        self.assertEqual(
            caught.exception.code,
            pgn_roundtrip.PgnRoundTripErrorCode.MALFORMED_HEADER,
        )

    def test_failed_epd_parse_does_not_replace_existing_canonical_record(self) -> None:
        existing = epd.parse_epd(_START_EPD)
        existing_text = existing.to_epd()

        with self.assertRaises(epd.EpdParseError):
            epd.parse_epd(_START_EPD + " hmvc 2")

        self.assertEqual(existing.to_epd(), existing_text)
        self.assertEqual(existing.position.to_fen(), _START_EPD + " 0 1")


if __name__ == "__main__":
    unittest.main()
