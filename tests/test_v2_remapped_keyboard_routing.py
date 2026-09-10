from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.version2_profile import build_version2_router, build_version2_webview_adapter
from acs.version2_release_app import _share_v2_action_registry
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from tests.test_version2_release_ui import _Application


class _RoutingApplication(_Application):
    """Small V2 router fixture that records the canonical delegate path."""

    def __init__(self) -> None:
        super().__init__()
        self.routed: list[tuple[str, dict[str, object]]] = []
        registry = self.adapter.registry
        self.router = build_version2_router(self.shell, self._route, registry=registry)
        self.adapter = build_version2_webview_adapter(self.shell, self.router)

    def _route(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        self.routed.append((action, dict(payload)))
        return {"action": action, "payload": dict(payload)}


class Version2RemappedKeyboardRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(self.temp.name) / "keymap.json"
        )
        self.application = _RoutingApplication()
        _share_v2_action_registry(self.api, self.application)
        self.api.bind_version2_application(self.application)
        self.registry = self.application.adapter.registry

    def resolve_and_dispatch(self, context: str, binding: str) -> tuple[dict, dict]:
        resolved = self.api.keymap_resolve_binding(context, binding)
        self.assertIsNotNone(resolved)
        result = self.api.dispatch_action(resolved["actionId"])
        self.assertTrue(result.get("ok"))
        return resolved, result

    def test_v2_and_stage1_share_exactly_one_registry(self) -> None:
        self.assertIs(self.api.keymap_service.editor.registry, self.application.adapter.registry)

    def test_global_remap_executes_through_v2_application_router(self) -> None:
        self.registry.set_binding("screen.library", "Ctrl+Alt+L", allow_warnings=True)

        resolved, result = self.resolve_and_dispatch("document", "Ctrl+Alt+L")

        self.assertEqual(resolved["actionId"], "screen.library")
        self.assertEqual(resolved["context"], "global")
        self.assertEqual(self.application.shell.current_route.route_id, "library")
        self.assertTrue(any(event["kind"] == "route" for event in self.application.events))
        for key in (
            "lang",
            "gameInfo",
            "moves",
            "whitePieces",
            "blackPieces",
            "gameStatus",
            "fen",
            "board",
        ):
            self.assertIn(key, result)
        self.assertEqual(len(result["board"]), 64)
        self.assertEqual(result["announcement"], "")
        self.assertEqual(result["v2"]["kind"], "route")

    def test_database_remap_executes_through_same_router_on_library_route(self) -> None:
        self.registry.set_binding("library.next_page", "Ctrl+Alt+N", allow_warnings=True)
        self.api.dispatch_action("screen.library")

        resolved, result = self.resolve_and_dispatch("document", "Ctrl+Alt+N")

        self.assertEqual(resolved["actionId"], "library.next_page")
        self.assertEqual(resolved["context"], "database")
        self.assertEqual(self.application.routed[-1][0], "library.next_page")
        self.assertEqual(result["v2"]["kind"], "action")

    def test_book_reader_remap_executes_through_same_router_on_books_route(self) -> None:
        self.registry.set_binding("book.next_heading", "Ctrl+Alt+H", allow_warnings=True)
        self.api.dispatch_action("screen.books")

        resolved, result = self.resolve_and_dispatch("document", "Ctrl+Alt+H")

        self.assertEqual(resolved["actionId"], "book.next_heading")
        self.assertEqual(resolved["context"], "book_reader")
        self.assertEqual(self.application.routed[-1][0], "book.next_heading")
        self.assertEqual(result["v2"]["kind"], "action")

    def test_conflicting_cross_context_remaps_follow_dynamic_route_precedence(self) -> None:
        chord = "Ctrl+Alt+R"
        self.registry.set_binding("screen.library", chord, allow_warnings=True)
        self.registry.set_binding("library.next_page", chord, allow_warnings=True)
        self.registry.set_binding("book.next_heading", chord, allow_warnings=True)

        initial = self.api.keymap_resolve_binding("document", chord)
        self.assertEqual(initial["actionId"], "screen.library")
        self.assertEqual(initial["context"], "global")
        self.api.dispatch_action(initial["actionId"])
        self.assertEqual(self.application.shell.current_route.route_id, "library")

        library = self.api.keymap_resolve_binding("document", chord)
        self.assertEqual(library["actionId"], "library.next_page")
        self.assertEqual(library["context"], "database")
        self.api.dispatch_action(library["actionId"])
        self.assertEqual(self.application.routed[-1][0], "library.next_page")

        self.api.dispatch_action("screen.books")
        books = self.api.keymap_resolve_binding("document", chord)
        self.assertEqual(books["actionId"], "book.next_heading")
        self.assertEqual(books["context"], "book_reader")
        self.api.dispatch_action(books["actionId"])
        self.assertEqual(self.application.routed[-1][0], "book.next_heading")

        self.api.dispatch_action("screen.board")
        back_to_global = self.api.keymap_resolve_binding("document", chord)
        self.assertEqual(back_to_global["actionId"], "screen.library")
        self.assertEqual(back_to_global["context"], "global")

    def test_exact_stage1_document_binding_still_beats_global_v2_conflict(self) -> None:
        chord = "Ctrl+Alt+G"
        self.registry.set_binding("pgn.next_game", chord, allow_warnings=True)
        self.registry.set_binding("screen.library", chord, allow_warnings=True)

        resolved = self.api.keymap_resolve_binding("document", chord)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "pgn.next_game")
        self.assertEqual(resolved["context"], "document")

    def test_alias_conflict_uses_same_dynamic_route_rule(self) -> None:
        alias = "next-item"
        self.registry.set_alias("screen.library", alias)
        self.registry.set_alias("library.next_page", alias)

        global_value = self.api.keymap_resolve_alias("document", alias)
        self.assertEqual(global_value["actionId"], "screen.library")
        self.api.dispatch_action(global_value["actionId"])

        library_value = self.api.keymap_resolve_alias("document", alias)
        self.assertEqual(library_value["actionId"], "library.next_page")
        self.assertEqual(library_value["context"], "database")

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

    def test_v2_board_dispatch_bypasses_v2_keyboard_override(self) -> None:
        stage1 = self.api.v2_board_dispatch("board.current", {"square": "e2"})

        self.assertTrue(stage1["ok"])
        self.assertEqual(stage1["focusSquare"], "e2")
        self.assertNotIn("v2", stage1)

    def test_without_v2_binding_stage1_behavior_remains_unchanged(self) -> None:
        unresolved = self.api.keymap_resolve_binding("document", "Ctrl+Alt+Shift+F12")
        self.assertIsNone(unresolved)


if __name__ == "__main__":
    unittest.main()
