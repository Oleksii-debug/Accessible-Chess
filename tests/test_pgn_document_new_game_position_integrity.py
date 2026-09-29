from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from acs.position_editor import PositionState, standard_position


CUSTOM_FEN = "7k/8/8/8/8/8/5K2/8 b - - 0 23"
CUSTOM_POSITION = f"""[Event "Custom black start"]
[SetUp "1"]
[FEN "{CUSTOM_FEN}"]
[Result "*"]

23... Kg7 24. Ke3 *
"""


class PgnDocumentNewGamePositionIntegrityTests(unittest.TestCase):
    def test_generic_new_game_tags_cannot_create_or_split_start_position(self) -> None:
        cases = (
            {"SetUp": "1"},
            {"FEN": CUSTOM_FEN},
            {"SetUp": "1", "FEN": CUSTOM_FEN},
        )

        for supplied in cases:
            with self.subTest(tags=supplied):
                original = dict(supplied)
                with self.assertRaises(PgnDocumentError) as caught:
                    PgnDocumentSession.new_game(supplied)
                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)
                self.assertEqual(supplied, original)

    def test_generic_new_game_still_accepts_descriptive_metadata(self) -> None:
        session = PgnDocumentSession.new_game(
            {
                "Event": "Fresh analysis",
                "White": "Alpha",
                "Black": "Beta",
                "Annotator": "Accessible Chess",
                "Result": "*",
            }
        )

        game = session.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Fresh analysis")
        self.assertEqual(game.tags["White"], "Alpha")
        self.assertEqual(game.tags["Black"], "Beta")
        self.assertEqual(game.tags["Annotator"], "Accessible Chess")
        self.assertNotIn("SetUp", game.tags)
        self.assertNotIn("FEN", game.tags)

    def test_invalid_generic_metadata_stays_in_document_error_domain(self) -> None:
        cases = (
            {"Bad Tag": "value"},
            {"Event": "line one\nline two"},
        )

        for supplied in cases:
            with self.subTest(tags=supplied):
                with self.assertRaises(PgnDocumentError) as caught:
                    PgnDocumentSession.new_game(supplied)
                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)
                self.assertNotIn("workspace", str(caught.exception).lower())

    def test_invalid_result_keeps_specific_result_error(self) -> None:
        with self.assertRaises(PgnDocumentError) as caught:
            PgnDocumentSession.new_game({"Result": "draw"})
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_RESULT)

    def test_position_workflow_creates_atomic_black_to_move_custom_start(self) -> None:
        position = PositionState.from_fen(CUSTOM_FEN)
        supplied = {
            "Event": "Position workflow",
            "White": "Alpha",
            "Black": "Beta",
            "Result": "*",
        }
        original = dict(supplied)

        session = PgnDocumentSession.new_game_from_position(position, supplied)

        game = session.workspace.current_game()
        self.assertEqual(supplied, original)
        self.assertEqual(game.tags["Event"], "Position workflow")
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"], CUSTOM_FEN)
        self.assertEqual(game.line.result, "*")
        self.assertTrue(session.dirty)
        self.assertIn('[SetUp "1"]', session.copy_pgn())
        self.assertIn(f'[FEN "{CUSTOM_FEN}"]', session.copy_pgn())

    def test_position_workflow_standard_start_does_not_add_setup_fen(self) -> None:
        session = PgnDocumentSession.new_game_from_position(
            standard_position(),
            {"Event": "Standard position"},
        )
        game = session.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Standard position")
        self.assertNotIn("SetUp", game.tags)
        self.assertNotIn("FEN", game.tags)

    def test_position_workflow_uses_canonical_board_fen_validation(self) -> None:
        structurally_editable_but_not_board_valid = PositionState.from_fen(
            "8/8/8/8/8/8/8/8 w - - 0 1"
        )
        with self.assertRaises(PgnDocumentError) as caught:
            PgnDocumentSession.new_game_from_position(
                structurally_editable_but_not_board_valid,
                {"Event": "Rejected position"},
            )
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_POSITION)

    def test_position_workflow_rejects_noncanonical_position_object(self) -> None:
        with self.assertRaises(PgnDocumentError) as caught:
            PgnDocumentSession.new_game_from_position(CUSTOM_FEN)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_POSITION)

    def test_position_workflow_cannot_smuggle_position_tags_through_metadata(self) -> None:
        position = PositionState.from_fen(CUSTOM_FEN)
        for supplied in (
            {"SetUp": "1"},
            {"FEN": CUSTOM_FEN},
            {"SetUp": "1", "FEN": CUSTOM_FEN},
        ):
            with self.subTest(tags=supplied):
                with self.assertRaises(PgnDocumentError) as caught:
                    PgnDocumentSession.new_game_from_position(position, supplied)
                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)

    def test_position_workflow_preserves_metadata_error_specificity(self) -> None:
        position = PositionState.from_fen(CUSTOM_FEN)
        with self.assertRaises(PgnDocumentError) as caught:
            PgnDocumentSession.new_game_from_position(position, {"Result": "draw"})
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_RESULT)

    def test_position_workflow_custom_start_survives_save_and_reopen(self) -> None:
        session = PgnDocumentSession.new_game_from_position(
            PositionState.from_fen(CUSTOM_FEN),
            {"Event": "Saved custom start"},
        )

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "custom position.pgn"
            session.save_as(target)
            self.assertFalse(session.dirty)

            reopened = PgnDocumentSession.open(target)
            self.assertFalse(reopened.dirty)
            game = reopened.workspace.current_game()
            self.assertEqual(game.tags["Event"], "Saved custom start")
            self.assertEqual(game.tags["SetUp"], "1")
            self.assertEqual(game.tags["FEN"], CUSTOM_FEN)
            self.assertEqual(game.line.result, "*")

    def test_existing_canonical_custom_start_pgn_ingress_is_unchanged(self) -> None:
        session = PgnDocumentSession.from_text(CUSTOM_POSITION)
        game = session.workspace.current_game()

        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"], CUSTOM_FEN)
        self.assertEqual(game.line.moves[0].move_number, "23...")
        self.assertEqual(game.line.moves[0].san, "Kg7")


if __name__ == "__main__":
    unittest.main()
