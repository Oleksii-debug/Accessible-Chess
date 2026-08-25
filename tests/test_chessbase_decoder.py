from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from acs.gametree_navigation import VariationStep, resolve_line


BACKEND_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def move(frm: int, to: int, promote: int = 7, comments=None) -> dict[str, object]:
    return {
        "kind": "move",
        "from": frm,
        "to": to,
        "promote": promote,
        "comments": [] if comments is None else comments,
    }


def decoded_game(index: int, moves: list[dict[str, object]], **overrides) -> dict[str, object]:
    record: dict[str, object] = {
        "index": index,
        "status": "decoded",
        "start_fen": START_FEN,
        "result": 1,
        "white_first": "Ada",
        "white_last": "White",
        "black_first": "Boris",
        "black_last": "Black",
        "event": "External Fixture",
        "site": "Test Lab",
        "year": 2026,
        "month": 8,
        "day": 24,
        "white_elo": 2400,
        "black_elo": 2300,
        "eco": 1,
        "round": 3,
        "subround": 2,
        "tags": [{"name": "Source", "value": "Pinned external oracle"}],
        "moves": moves,
    }
    record.update(overrides)
    return record


def payload(games: list[dict[str, object]], commit: str = BACKEND_COMMIT) -> bytes:
    return json.dumps(
        {
            "protocol": "accessible-chess-libcbh-v1",
            "backend": "libcbh",
            "backend_commit": commit,
            "games": games,
        },
        separators=(",", ":"),
    ).encode("utf-8")


class ChessBaseExternalDecoderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Fixture.cbh"
        self.source.write_bytes(b"CBH fixture bytes")
        self.cbg = self.root / "Fixture.cbg"
        self.cbg.write_bytes(b"CBG fixture bytes")
        self.backend = self.root / "decoder-backend"
        self.backend.write_bytes(b"external backend placeholder")
        self.config = ExternalChessBaseDecoderConfig(
            self.backend,
            expected_backend_commit=BACKEND_COMMIT,
            timeout_seconds=3,
        )

    def decode(self, backend_payload: bytes):
        with mock.patch("acs.chessbase_decoder._run_backend", return_value=backend_payload):
            return decode_chessbase_external(self.source, self.config)

    def test_flat_moves_are_revalidated_by_canonical_board_and_become_san(self) -> None:
        result = self.decode(
            payload([decoded_game(0, [move(12, 28), move(52, 36)])])
        )
        self.assertEqual(result.backend_name, "libcbh")
        self.assertEqual(result.backend_commit, BACKEND_COMMIT)
        self.assertEqual(result.total_games, 1)
        game = result.games[0]
        self.assertEqual([node.san for node in game.line.moves], ["e4", "e5"])
        self.assertEqual([node.move_number for node in game.line.moves], ["1.", "1..."])
        self.assertEqual(game.tags["White"], "Ada White")
        self.assertEqual(game.tags["Black"], "Boris Black")
        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.tags["Round"], "3.2")
        self.assertEqual(game.tags["Source"], "Pinned external oracle")
        self.assertEqual(game.line.result, "1-0")

    def test_push_pop_sequence_builds_sibling_variations_from_current_position(self) -> None:
        tokens = [
            move(12, 28),  # 1. e4
            {"kind": "push"},
            move(50, 34),  # 1... c5
            {"kind": "pop"},
            {"kind": "push"},
            move(50, 42),  # 1... c6
            {"kind": "pop"},
            move(52, 36),  # 1... e5 main line
            move(6, 21),   # 2. Nf3
        ]
        result = self.decode(payload([decoded_game(0, tokens)]))
        game = result.games[0]
        self.assertEqual([node.san for node in game.line.moves], ["e4", "e5", "Nf3"])
        self.assertEqual(len(game.line.moves[0].variations), 2)
        first = resolve_line(game, (VariationStep(0, 0),))
        second = resolve_line(game, (VariationStep(0, 1),))
        self.assertEqual([node.san for node in first.moves], ["c5"])
        self.assertEqual([node.san for node in second.moves], ["c6"])

    def test_nested_variation_is_preserved_recursively(self) -> None:
        tokens = [
            move(12, 28),
            {"kind": "push"},
            move(50, 34),
            {"kind": "push"},
            move(6, 21),
            {"kind": "pop"},
            move(6, 21),
            {"kind": "pop"},
            move(52, 36),
        ]
        game = self.decode(payload([decoded_game(0, tokens)])).games[0]
        outer = resolve_line(game, (VariationStep(0, 0),))
        nested = resolve_line(game, (VariationStep(0, 0), VariationStep(0, 0)))
        self.assertEqual([node.san for node in outer.moves], ["c5", "Nf3"])
        self.assertEqual([node.san for node in nested.moves], ["Nf3"])

    def test_text_symbol_and_graphic_annotations_survive_neutral_conversion(self) -> None:
        comments = [
            {"kind": "text_before", "lang": 0, "text": "before"},
            {"kind": "text_after", "lang": 53, "text": "nach Zug"},
            {"kind": "symbol", "symbol": 1, "evaluation": 14, "prefix": 36},
            {"kind": "arrow", "from": 12, "to": 28, "color": "green"},
            {"kind": "square", "square": 28, "color": "yellow"},
        ]
        game = self.decode(payload([decoded_game(0, [move(12, 28, comments=comments)])])).games[0]
        node = game.line.moves[0]
        self.assertEqual([item.text for item in node.comments_before], ["before"])
        after = [item.text for item in node.comments_after]
        self.assertIn("[%cbh-lang 53] nach Zug", after)
        self.assertIn("[%cbh-arrow green e2e4]", after)
        self.assertIn("[%cbh-square yellow e4]", after)
        self.assertEqual(node.nags, ["$1", "$14", "$36"])

    def test_illegal_backend_move_fails_closed_instead_of_becoming_game_data(self) -> None:
        with self.assertRaises(ChessBaseDecodeError) as caught:
            self.decode(payload([decoded_game(0, [move(12, 44)])]))
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.INVALID_MOVE)

    def test_unmatched_pop_and_unterminated_push_fail_closed(self) -> None:
        for tokens in (
            [{"kind": "pop"}],
            [move(12, 28), {"kind": "push"}, move(50, 34)],
        ):
            with self.subTest(tokens=tokens):
                with self.assertRaises(ChessBaseDecodeError) as caught:
                    self.decode(payload([decoded_game(0, tokens)]))
                self.assertEqual(caught.exception.code, ChessBaseDecodeCode.INVALID_VARIATION)

    def test_skipped_backend_record_is_explicit_warning_not_fabricated_game(self) -> None:
        result = self.decode(
            payload(
                [
                    {"index": 0, "status": "skipped", "error_code": 7},
                    decoded_game(1, [move(11, 27), move(51, 35)]),
                ]
            )
        )
        self.assertEqual(result.total_games, 1)
        self.assertEqual(result.games[0].source_index, 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].game_index, 0)
        self.assertEqual(result.warnings[0].code, "backend_record_skipped")

    def test_duplicate_json_keys_are_rejected(self) -> None:
        raw = (
            '{"protocol":"accessible-chess-libcbh-v1",'
            '"protocol":"other","backend":"libcbh",'
            f'"backend_commit":"{BACKEND_COMMIT}","games":[]}}'
        ).encode("utf-8")
        with self.assertRaises(ChessBaseDecodeError) as caught:
            self.decode(raw)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.PROTOCOL_ERROR)

    def test_backend_commit_is_pinned_by_configuration(self) -> None:
        other = "0" * 40
        with self.assertRaises(ChessBaseDecodeError) as caught:
            self.decode(payload([], commit=other))
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.PROTOCOL_ERROR)

    def test_source_family_mutation_during_backend_execution_invalidates_output(self) -> None:
        good = payload([decoded_game(0, [move(12, 28)])])

        def mutate(*_args, **_kwargs):
            self.cbg.write_bytes(b"changed while decoder was running")
            return good

        with mock.patch("acs.chessbase_decoder._run_backend", side_effect=mutate):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                decode_chessbase_external(self.source, self.config)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.SOURCE_CHANGED)

    def test_non_cbh_family_is_not_promoted_to_semantic_support(self) -> None:
        cbv = self.root / "Archive.cbv"
        cbv.write_bytes(b"archive")
        with self.assertRaises(ChessBaseDecodeError) as caught:
            decode_chessbase_external(cbv, self.config)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.UNSUPPORTED_SOURCE)

    def test_nonstandard_start_position_is_preserved_as_setup_fen(self) -> None:
        fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
        record = decoded_game(
            0,
            [move(12, 20)],
            start_fen=fen,
            result=0,
        )
        game = self.decode(payload([record])).games[0]
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"], fen)
        self.assertEqual(game.line.moves[0].san, "e3")
        self.assertEqual(game.line.result, "*")


if __name__ == "__main__":
    unittest.main()
