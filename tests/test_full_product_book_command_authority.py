from __future__ import annotations

import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.version2_application import Version2Application


class FullProductBookCommandAuthorityTests(unittest.TestCase):
    def test_book_progress_transaction_set_includes_bidirectional_semantic_navigation(self):
        self.assertEqual(
            Version2Application._BOOK_PROGRESS_COMMANDS,
            frozenset(
                {
                    "book.previous",
                    "book.next",
                    "book.previous_heading",
                    "book.next_heading",
                    "book.previous_position",
                    "book.next_position",
                    "book.previous_game",
                    "book.next_game",
                    "book.bookmark.save",
                    "book.bookmark.restore",
                }
            ),
        )

    def test_book_board_active_command_set_matches_canonical_adapter_commands(self):
        self.assertEqual(
            Version2Application._BOOK_BOARD_ACTIVE_COMMANDS,
            frozenset(
                {
                    "book.board_next_move",
                    "book.board_previous_move",
                    "book.board_enter_variation",
                    "book.board_leave_variation",
                    "book.board_analyze",
                }
            ),
        )

    def test_book_game_launch_is_registered_for_webview_dispatch(self):
        action = build_full_product_action_registry().definition("book.open_game")
        self.assertEqual("book.open_game", action.action_id)


if __name__ == "__main__":
    unittest.main()
