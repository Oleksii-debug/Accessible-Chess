from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.keybindings import BindingContext
from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from acs.position_editor import PositionState, standard_position
from acs.version2_application import Version2Application
from acs.version2_profile import build_version2_action_registry, build_version2_menu_spec
from acs.version2_release_app import _current_display_position
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


CUSTOM_FEN = "7k/8/8/8/8/8/5K2/8 b - - 0 23"


class PgnPositionNewDocumentReachabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.current_position = PositionState.from_fen(CUSTOM_FEN)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
            board_position_provider=lambda: self.current_position,
        )
        self.addCleanup(self.app.shutdown)

    def test_action_is_board_scoped_remappable_and_has_no_forced_default_hotkey(self) -> None:
        registry = build_version2_action_registry()
        definition = registry.definition("pgn.new_from_position")

        self.assertIs(definition.context, BindingContext.BOARD)
        self.assertIsNone(registry.get_binding("pgn.new_from_position"))

        registry.set_binding("pgn.new_from_position", "Ctrl+Alt+N")
        resolved = registry.resolve_binding(BindingContext.BOARD, "Ctrl+Alt+N")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.action_id, "pgn.new_from_position")
        self.assertIs(resolved.context, BindingContext.BOARD)

    def test_native_position_menu_exposes_localized_action(self) -> None:
        registry = build_version2_action_registry()

        english = build_version2_menu_spec(registry, language="en")
        ukrainian = build_version2_menu_spec(registry, language="uk")

        def item_label(spec):
            position = next(menu for menu in spec if menu.menu_id == "position")
            return next(
                item.label
                for item in position.items
                if item.action_id == "pgn.new_from_position"
            )

        self.assertEqual(item_label(english), "Create PGN from current position")
        self.assertEqual(item_label(ukrainian), "Створити PGN з поточної позиції")

    def test_adapter_action_creates_dirty_custom_start_document_and_opens_pgn(self) -> None:
        command = self.app.adapter.activate_action(
            "pgn.new_from_position",
            current_focus_id="board-launcher",
        )

        self.assertEqual(command.kind, "delegated")
        self.assertTrue(self.app.native_command(command))
        self.assertIsNotNone(self.app.session)
        self.assertTrue(self.app.session.dirty)
        game = self.app.session.workspace.current_game()
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"], CUSTOM_FEN)
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        self.assertFalse(self.app.pgn_board_active)

    def test_standard_position_does_not_publish_redundant_setup_fen(self) -> None:
        self.current_position = standard_position()

        self.app.router.dispatch("pgn.new_from_position")

        game = self.app.session.workspace.current_game()
        self.assertNotIn("SetUp", game.tags)
        self.assertNotIn("FEN", game.tags)

    def test_dirty_replacement_confirmation_is_required_once_and_cancel_is_atomic(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Unsaved existing"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        before_text = existing.copy_pgn()
        calls = []

        def reject() -> bool:
            calls.append(True)
            return False

        self.app.confirm_document_replace = reject

        with self.assertRaisesRegex(ValueError, "replacement cancelled"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(calls, [True])
        self.assertIs(self.app.session, existing)
        self.assertEqual(self.app.session.copy_pgn(), before_text)
        self.assertEqual(self.app.shell.current_route.route_id, "board")


    def test_route_publication_failure_keeps_existing_document_authoritative(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Unsaved existing"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        existing_bridge = self.app.pgn
        existing_text = existing.copy_pgn()
        self.app.confirm_document_replace = lambda: True

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=RuntimeError("synthetic PGN route publication failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "route publication failure"):
                self.app.router.dispatch("pgn.new_from_position")

        self.assertIs(self.app.session, existing)
        self.assertIs(self.app.pgn, existing_bridge)
        self.assertEqual(self.app.session.copy_pgn(), existing_text)
        self.assertTrue(self.app.session.dirty)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertFalse(self.app.pgn_board_active)

    def test_dirty_replacement_confirmation_accepts_and_swaps_once(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Unsaved existing"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        calls = []

        def accept() -> bool:
            calls.append(True)
            return True

        self.app.confirm_document_replace = accept

        self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(calls, [True])
        self.assertIsNot(self.app.session, existing)
        self.assertEqual(self.app.session.workspace.current_game().tags["FEN"], CUSTOM_FEN)

    def test_canonical_position_rejection_never_enters_replacement_or_swaps_document(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Keep active document"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        existing_bridge = self.app.pgn
        existing_text = existing.copy_pgn()
        confirmations: list[bool] = []

        self.app.confirm_document_replace = lambda: confirmations.append(True) or True
        self.current_position = PositionState.from_fen("8/8/8/8/8/8/8/8 w - - 0 1")

        with self.assertRaises(PgnDocumentError) as caught:
            self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_POSITION)
        self.assertEqual(confirmations, [])
        self.assertIs(self.app.session, existing)
        self.assertIs(self.app.pgn, existing_bridge)
        self.assertEqual(self.app.session.copy_pgn(), existing_text)
        self.assertTrue(self.app.session.dirty)
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_invalid_position_provider_never_replaces_document(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Keep me"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        self.app.confirm_document_replace = lambda: True
        self.app._board_position_provider = lambda: CUSTOM_FEN

        with self.assertRaisesRegex(TypeError, "invalid state"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertIs(self.app.session, existing)
        self.assertIn('[Event "Keep me"]', existing.copy_pgn())

    def test_positionstate_subclass_provider_is_rejected_before_custom_method_dispatch(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Keep exact provider authority"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        self.app.confirm_document_replace = lambda: True
        canonical = standard_position()

        class ForgedPosition(PositionState):
            def to_fen(self) -> str:
                raise AssertionError("subclass to_fen must not execute")

        forged = ForgedPosition(
            canonical.pieces,
            turn=canonical.turn,
            castling=canonical.castling,
            en_passant=canonical.en_passant,
            halfmove=canonical.halfmove,
            fullmove=canonical.fullmove,
        )
        self.app._board_position_provider = lambda: forged

        with self.assertRaisesRegex(TypeError, "invalid state"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertIs(self.app.session, existing)
        self.assertIn('[Event "Keep exact provider authority"]', existing.copy_pgn())
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_provider_failure_never_replaces_document(self) -> None:
        existing = PgnDocumentSession.new_game({"Event": "Keep me"})
        self.app.set_document(existing)
        self.app.shell.open_route("board")
        self.app.confirm_document_replace = lambda: True

        def fail():
            raise RuntimeError("synthetic board provider failure")

        self.app._board_position_provider = fail

        with self.assertRaisesRegex(RuntimeError, "synthetic board provider failure"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertIs(self.app.session, existing)

    def test_hidden_board_route_is_rejected_before_provider_acquisition(self) -> None:
        calls = []
        self.app._board_position_provider = lambda: calls.append(True) or self.current_position
        self.app.shell.open_route("library")

        with self.assertRaisesRegex(ValueError, "visible Board"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(calls, [])
        self.assertIsNone(self.app.session)
        self.assertEqual(self.app.shell.current_route.route_id, "library")

    def test_modal_focus_blocks_provider_acquisition_and_document_publication(self) -> None:
        calls = []
        self.app._board_position_provider = lambda: calls.append(True) or self.current_position
        dialog = self.app.adapter.open_dialog(
            "position-modal",
            opener_focus_id="board-launcher",
            initial_focus_id="position-modal-confirm",
        )
        self.assertEqual(dialog.kind, "dialog-open")

        with self.assertRaisesRegex(ValueError, "active dialog"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(calls, [])
        self.assertIsNone(self.app.session)
        self.assertEqual(self.app.shell.active_dialog_id, "position-modal")
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_active_book_board_ownership_blocks_provider_acquisition_and_document_publication(self) -> None:
        calls = []
        self.app._board_position_provider = lambda: calls.append(True) or self.current_position
        self.app.book_workflow = SimpleNamespace(active=True)

        with self.assertRaisesRegex(ValueError, "return to the book"):
            self.app.router.dispatch("pgn.new_from_position")

        self.assertEqual(calls, [])
        self.assertIsNone(self.app.session)
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_release_provider_materializes_visible_board_without_browser_state(self) -> None:
        api = object.__new__(Version2ReleaseAccessibleChessAPI)
        visible = Board(CUSTOM_FEN)
        with patch.object(api, "_display_board", return_value=visible):
            position = _current_display_position(api)

        self.assertIsInstance(position, PositionState)
        self.assertEqual(position.to_fen(), CUSTOM_FEN)


    def test_reachability_workflow_tracks_application_regression(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "pgn-position-new-document-reachability.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("'tests/test_version2_application.py'", workflow)
        self.assertIn("tests.test_version2_application", workflow)


if __name__ == "__main__":
    unittest.main()
