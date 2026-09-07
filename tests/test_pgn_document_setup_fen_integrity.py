from __future__ import annotations

import unittest

from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession


CUSTOM_POSITION = '''[Event "Custom start"]
[SetUp "1"]
[FEN "7k/8/8/8/8/8/8/K7 w - - 0 1"]
[Result "*"]

*
'''


class PgnDocumentSetupFenIntegrityTests(unittest.TestCase):
    def test_generic_tag_editor_cannot_break_start_position_pair(self) -> None:
        operations = (
            lambda session: session.delete_tag("SetUp"),
            lambda session: session.delete_tag("FEN"),
            lambda session: session.edit_tag("SetUp", "0"),
            lambda session: session.edit_tag(
                "FEN", "7k/8/8/8/8/8/K7/8 b - - 0 1"
            ),
        )

        for operation in operations:
            with self.subTest(operation=operation):
                session = PgnDocumentSession.from_text(CUSTOM_POSITION)
                before_text = session.copy_pgn()
                before_view = session.view()

                with self.assertRaises(PgnDocumentError) as caught:
                    operation(session)

                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)
                self.assertEqual(session.copy_pgn(), before_text)
                self.assertEqual(session.view(), before_view)

    def test_normal_metadata_tags_remain_editable(self) -> None:
        session = PgnDocumentSession.from_text(CUSTOM_POSITION)
        session.edit_tag("Event", "Edited metadata")
        self.assertEqual(session.workspace.current_game().tags["Event"], "Edited metadata")
        self.assertEqual(session.workspace.current_game().tags["SetUp"], "1")
        self.assertEqual(
            session.workspace.current_game().tags["FEN"],
            "7k/8/8/8/8/8/8/K7 w - - 0 1",
        )


if __name__ == "__main__":
    unittest.main()
