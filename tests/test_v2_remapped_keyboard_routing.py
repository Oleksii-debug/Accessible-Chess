from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.version2_release_app import _share_v2_action_registry
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from tests.test_version2_release_ui import _Application


class Version2RemappedKeyboardRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(self.temp.name) / "keymap.json"
        )
        self.application = _Application()
        _share_v2_action_registry(self.api, self.application)
        self.api.bind_version2_application(self.application)
        self.registry = self.application.adapter.registry

    def test_inherited_document_handler_resolves_global_v2_binding_and_routes_it(self) -> None:
        """The unchanged Stage1 handler's final document lookup must reach V2 GLOBAL."""
        self.registry.set_binding("screen.library", "Ctrl+Alt+L", allow_warnings=True)

        resolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+L")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "screen.library")
        result = self.api.dispatch_action(resolved["actionId"])
        self.assertTrue(result.get("ok"))
        self.assertEqual(self.application.shell.current_route.route_id, "library")
        self.assertTrue(any(event["kind"] == "route" for event in self.application.events))

    def test_library_route_uses_database_context_before_global(self) -> None:
        self.registry.set_binding("library.next_page", "Ctrl+Alt+N", allow_warnings=True)
        self.api.dispatch_action("screen.library")

        resolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+N")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "library.next_page")
        self.assertEqual(resolved["context"], "database")

    def test_books_route_uses_book_reader_context(self) -> None:
        self.registry.set_binding("book.next_heading", "Ctrl+Alt+H", allow_warnings=True)
        self.api.dispatch_action("screen.books")

        resolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+H")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "book.next_heading")
        self.assertEqual(resolved["context"], "book_reader")

    def test_book_review_board_context_keeps_book_shortcuts_executable(self) -> None:
        self.registry.set_binding("book.board_next_move", "Ctrl+Alt+B", allow_warnings=True)
        self.application.book_workflow = SimpleNamespace(active=True)
        self.application.shell.open_route("board")

        resolved = self.api.keymap_resolve_binding("board", "Ctrl+Alt+B")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "book.board_next_move")
        self.assertEqual(resolved["context"], "book_reader")

    def test_pgn_review_board_context_keeps_document_shortcuts_executable(self) -> None:
        self.registry.set_binding("pgn.board_next_move", "Ctrl+Alt+P", allow_warnings=True)
        self.application.book_workflow = SimpleNamespace(active=False)
        self.application.pgn_board_active = True
        self.application.shell.open_route("board")

        resolved = self.api.keymap_resolve_binding("board", "Ctrl+Alt+P")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "pgn.board_next_move")
        self.assertEqual(resolved["context"], "document")

    def test_stage1_direct_context_keeps_precedence_over_v2_global_fallback(self) -> None:
        self.registry.set_binding("pgn.next_game", "Ctrl+Alt+G", allow_warnings=True)
        self.registry.set_binding("screen.library", "Ctrl+Alt+G", allow_warnings=True)

        resolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+G")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "pgn.next_game")
        self.assertEqual(resolved["context"], "document")

    def test_without_v2_binding_stage1_behavior_remains_unchanged(self) -> None:
        unresolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+Shift+F12")
        self.assertIsNone(unresolved)

        stage1 = self.api.v2_board_dispatch("board.current", {"square": "e2"})
        self.assertTrue(stage1["ok"])
        self.assertEqual(stage1["focusSquare"], "e2")


if __name__ == "__main__":
    unittest.main()
