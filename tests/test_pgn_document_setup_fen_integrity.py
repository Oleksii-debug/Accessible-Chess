from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession


CUSTOM_POSITION = '''[Event "Custom black start"]
[SetUp "1"]
[FEN "7k/8/8/8/8/8/5K2/8 b - - 0 23"]
[Result "*"]

23... Kg7 24. Ke3 *
'''


class PgnDocumentSetupFenIntegrityTests(unittest.TestCase):
    def test_generic_tag_editor_cannot_break_start_position_pair(self) -> None:
        operations = (
            lambda session: session.delete_tag("SetUp"),
            lambda session: session.delete_tag("FEN"),
            lambda session: session.edit_tag("SetUp", "0"),
            lambda session: session.edit_tag(
                "FEN", "7k/8/8/8/8/8/K7/8 w - - 0 1"
            ),
        )

        for operation in operations:
            with self.subTest(operation=operation):
                session = PgnDocumentSession.from_text(CUSTOM_POSITION)
                before_text = session.copy_pgn()
                before_document_view = session.view()
                before_workspace_view = session.workspace.view()

                with self.assertRaises(PgnDocumentError) as caught:
                    operation(session)

                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)
                self.assertEqual(session.copy_pgn(), before_text)
                self.assertEqual(session.view(), before_document_view)
                self.assertEqual(session.workspace.view(), before_workspace_view)

    def test_normal_metadata_remains_editable_without_changing_custom_start(self) -> None:
        session = PgnDocumentSession.from_text(CUSTOM_POSITION)
        session.edit_tag("Event", "Edited metadata")
        session.edit_tag("Annotator", "Accessible Chess")
        session.delete_tag("Annotator")

        game = session.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Edited metadata")
        self.assertNotIn("Annotator", game.tags)
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(
            game.tags["FEN"],
            "7k/8/8/8/8/8/5K2/8 b - - 0 23",
        )
        self.assertEqual(game.line.moves[0].move_number, "23...")
        self.assertEqual(game.line.moves[0].san, "Kg7")

    def test_custom_black_start_and_metadata_survive_save_reopen(self) -> None:
        session = PgnDocumentSession.from_text(CUSTOM_POSITION)
        session.edit_tag("Event", "Saved custom metadata")

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "custom black start.pgn"
            session.save_as(target)
            self.assertFalse(session.dirty)

            reopened = PgnDocumentSession.open(target)
            self.assertFalse(reopened.dirty)
            game = reopened.workspace.current_game()
            self.assertEqual(game.tags["Event"], "Saved custom metadata")
            self.assertEqual(game.tags["SetUp"], "1")
            self.assertEqual(
                game.tags["FEN"],
                "7k/8/8/8/8/8/5K2/8 b - - 0 23",
            )
            self.assertEqual(game.line.moves[0].move_number, "23...")
            self.assertEqual(game.line.moves[0].san, "Kg7")


if __name__ == "__main__":
    unittest.main()
