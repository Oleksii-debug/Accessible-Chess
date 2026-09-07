from __future__ import annotations

import unittest

from acs.gametree_navigation import GameTreeCursor
from acs.pgn_document import (
    PgnDocumentContext,
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)


DOCUMENT = '''[Event "First"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event "Second"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''


class PgnDocumentContextAtomicityTests(unittest.TestCase):
    def test_invalid_saved_cursor_does_not_partially_switch_selected_game(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace.set_cursor(GameTreeCursor((), 2))
        before = session.workspace.view()

        forged = PgnDocumentContext(
            content_digest=before.content_digest,
            selected_game_index=1,
            cursor=GameTreeCursor((), 999),
        )

        with self.assertRaises(PgnDocumentError) as caught:
            session.restore_context(forged)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertEqual(session.workspace.view(), before)

    def test_invalid_saved_game_index_does_not_mutate_current_location(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace.select_game(1)
        session.workspace.set_cursor(GameTreeCursor((), 1))
        before = session.workspace.view()

        forged = PgnDocumentContext(
            content_digest=before.content_digest,
            selected_game_index=99,
            cursor=GameTreeCursor(),
        )

        with self.assertRaises(PgnDocumentError) as caught:
            session.restore_context(forged)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertEqual(session.workspace.view(), before)


if __name__ == "__main__":
    unittest.main()
