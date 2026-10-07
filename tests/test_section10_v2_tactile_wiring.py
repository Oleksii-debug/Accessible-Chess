from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.pgn_document import PgnDocumentSession
from acs.tactile_graphics import TactileScene
from acs.tactile_sync import TactileSyncState
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.version2_application import Version2Application
from acs.version2_profile import build_version2_action_registry, build_version2_menu_spec


PGN = '[Event "Section10 V2"]\n\n1. e4 e5 *\n'


class _FailingDisplay:
    def present(self, scene: TactileScene) -> None:
        raise OSError("device detail must stay non-authoritative")


class _TrainingWorkspaceStub:
    def __init__(self, session: ExerciseSession) -> None:
        self.session = session
        self.bridge = object()
        self.language = UILanguage.UA

    def dispatch(self, command, payload=None):
        if command != "training.submit":
            raise AssertionError("unexpected training command")
        result = self.session.submit(str(payload))
        return SimpleNamespace(kind="training-result", result=result)


class Section10V2TactileWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.board_fen = Board().fen()
        self.board_calls = []

        def board_dispatch(action, payload):
            self.board_calls.append((action, payload))
            if action == "board.read_fen":
                return {"ok": True, "fen": self.board_fen}
            return {"ok": True}

        self.board_dispatch = board_dispatch
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=board_dispatch,
            board_position_projector=lambda fen: {"ok": True, "fen": fen},
        )

    def test_v2_registry_and_native_settings_menu_expose_accessible_tactile_commands(self):
        registry = build_version2_action_registry()
        ids = {definition.action_id for definition in registry.definitions()}
        self.assertIn("tactile.status", ids)
        self.assertIn("tactile.refresh", ids)

        spec = build_version2_menu_spec(registry, language=UILanguage.UA)
        settings = next(menu for menu in spec if menu.menu_id == "settings")
        action_ids = tuple(item.action_id for item in settings.items if item.action_id)
        self.assertIn("tactile.status", action_ids)
        self.assertIn("tactile.refresh", action_ids)

    def test_manual_refresh_and_status_are_keyboard_menu_reachable_and_announced(self):
        refreshed = self.app._delegate("tactile.refresh", {})
        self.assertEqual(refreshed["state"], "synced")
        self.assertEqual(refreshed["canonical_fen"], self.board_fen)
        self.assertEqual(
            self.app.tactile_graphics.current_scene.position_fen,
            self.board_fen,
        )

        status = self.app._delegate("tactile.status", {})
        self.assertEqual(status["state"], "synced")
        events = self.app.drain_events()
        announcements = [
            event.get("payload", {}).get("announcement")
            for event in events
            if event.get("kind") == "status"
        ]
        self.assertTrue(
            any(
                value == "Тактильну дошку синхронізовано з поточною позицією."
                for value in announcements
            )
        )

    def test_board_success_path_automatically_refreshes_tactile_scene(self):
        target = "7k/8/8/8/8/8/8/K7 b - - 17 42"
        self.board_fen = target

        result = self.app._delegate("move.empty", {})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.app.tactile_graphics.current_scene.position_fen, target)
        self.assertEqual(self.app.tactile_sync.snapshot().state, TactileSyncState.SYNCED)
        self.assertIn(("board.read_fen", {}), self.board_calls)

    def test_pgn_board_open_and_navigation_automatically_refresh_tactile_scene(self):
        self.app.set_document(PgnDocumentSession.from_text(PGN))

        self.app._delegate("pgn.open_on_board", {})
        before = self.app.tactile_graphics.current_scene
        self.assertIsNotNone(before)
        self.assertTrue(self.app.pgn_board_active)

        self.app._delegate("pgn.board_next_move", {})
        after = self.app.tactile_graphics.current_scene
        self.assertIsNotNone(after)
        self.assertNotEqual(before.position_fen, after.position_fen)
        self.assertGreater(after.sequence, before.sequence)

    def test_training_answer_automatically_refreshes_tactile_scene(self):
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-v2-training",
                start_fen=Board().fen(),
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )
        workspace = _TrainingWorkspaceStub(session)
        self.app.training_workspace = workspace
        self.app.training = workspace.bridge
        self.app.shell.open_route("training")

        self.app._dispatch_training_surface_command("training.submit", "e4")

        self.assertEqual(
            self.app.tactile_graphics.current_scene.position_fen,
            session.current_fen,
        )
        self.assertEqual(self.app.tactile_sync.snapshot().source.value, "training")

    def test_tactile_output_failure_never_rolls_back_successful_board_action(self):
        failing = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress-failing.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=self.board_dispatch,
            board_position_projector=lambda fen: {"ok": True, "fen": fen},
            tactile_display=_FailingDisplay(),
        )
        target = "7k/8/8/8/8/8/8/K7 b - - 17 42"
        self.board_fen = target

        result = failing._delegate("move.empty", {})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(failing.tactile_sync.snapshot().state, TactileSyncState.ERROR)
        self.assertIsNone(failing.tactile_graphics.current_scene)
        self.assertEqual(self.board_fen, target)


if __name__ == "__main__":
    unittest.main()
