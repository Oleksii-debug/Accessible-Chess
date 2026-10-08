from __future__ import annotations

import unittest

from acs.book_board_workflow import BookBoardMode, BookBoardView
from acs.bookreader import ReadingLocation
from acs.chesscore import Board
from acs.pgn_document import PgnDocumentSession
from acs.tactile_graphics import (
    TactileDisplayPort,
    TactileGraphicsController,
    TactileScene,
    TactileSimulator,
)
from acs.tactile_sync import (
    TactileSyncCommand,
    TactileSyncController,
    TactileSyncError,
    TactileSyncSource,
    TactileSyncState,
)
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


class _FailingDisplay:
    def present(self, scene: TactileScene) -> None:
        raise OSError("provider detail")


class Section10TactileSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.display = TactileSimulator()
        self.graphics = TactileGraphicsController(self.display)
        self.sync = TactileSyncController(self.graphics)

    def test_idle_status_and_section8_port_are_exact(self):
        self.assertIsInstance(self.display, TactileDisplayPort)
        status = self.sync.dispatch(TactileSyncCommand.STATUS)
        self.assertEqual(status.state, TactileSyncState.IDLE)
        self.assertEqual(status.status_key, "tactile.status.idle")
        self.assertIsNone(self.graphics.current_scene)

    def test_position_fen_is_projected_by_section8_not_reimplemented(self):
        fen = Board().fen()
        status = self.sync.sync_position(fen, source_revision=4)
        scene = self.display.current_scene

        self.assertIsNotNone(scene)
        self.assertEqual(scene.position_fen, fen)
        self.assertEqual(status.canonical_fen, fen)
        self.assertEqual(status.source, TactileSyncSource.POSITION)
        self.assertEqual(status.source_revision, 4)
        self.assertEqual(status.scene_sequence, scene.sequence)

        with self.assertRaises(TactileSyncError):
            self.sync.sync_position(" " + fen)
        self.assertEqual(self.display.current_scene, scene)

    def test_pgn_gametree_navigation_updates_section8_scene(self):
        session = PgnDocumentSession.from_text(
            '[Event "Section10"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
        )
        workspace = session.workspace

        start = self.sync.sync_pgn(workspace)
        start_scene = self.display.current_scene
        workspace.next_move()
        e4 = self.sync.sync_pgn(workspace)
        e4_scene = self.display.current_scene

        self.assertEqual(start.source, TactileSyncSource.PGN)
        self.assertEqual(e4.source, TactileSyncSource.PGN)
        self.assertNotEqual(start.canonical_fen, e4.canonical_fen)
        self.assertEqual(e4.canonical_fen, e4_scene.position_fen)
        self.assertGreater(e4_scene.sequence, start_scene.sequence)

        workspace.next_move()
        e5 = self.sync.dispatch(TactileSyncCommand.REFRESH_PGN, workspace)
        self.assertEqual(e5.canonical_fen, self.display.current_scene.position_fen)
        self.assertGreater(e5.scene_sequence, e4.scene_sequence)

    def test_book_board_view_projects_tactile_without_changing_return_origin(self):
        fen = Board().fen()
        origin = ReadingLocation(
            index=3,
            kind="Position",
            block_id="book-position-3",
            source_anchor="chapter-1-position-3",
            heading_path=("Chapter 1",),
            position_fen=fen,
            side_to_move="w",
        )
        view = BookBoardView(
            mode=BookBoardMode.POSITION,
            origin=origin,
            current_fen=fen,
            cursor=None,
            source=None,
            game_id=None,
            warnings=(),
            revision=9,
        )

        status = self.sync.sync_book_view(view)

        self.assertEqual(status.source, TactileSyncSource.BOOK)
        self.assertEqual(status.source_revision, 9)
        self.assertEqual(self.display.current_scene.position_fen, fen)
        self.assertEqual(view.origin, origin)
        self.assertEqual(view.origin.source_anchor, "chapter-1-position-3")

    def test_training_refreshes_after_accepted_answer(self):
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-training",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )

        before = self.sync.sync_training(session)
        result = session.submit("e4")
        self.assertTrue(result.accepted)
        after = self.sync.sync_training(session)

        self.assertEqual(before.source_revision, 0)
        self.assertEqual(after.source_revision, 1)
        self.assertNotEqual(before.canonical_fen, after.canonical_fen)
        self.assertEqual(after.canonical_fen, session.current_fen)
        self.assertEqual(after.canonical_fen, self.display.current_scene.position_fen)

    def test_training_refreshes_status_after_incorrect_answer_without_board_change(self):
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-training-wrong",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )

        before = self.sync.sync_training(session)
        result = session.submit("d4")
        self.assertFalse(result.accepted)
        after = self.sync.dispatch(TactileSyncCommand.REFRESH_TRAINING, session)

        self.assertEqual(before.canonical_fen, after.canonical_fen)
        self.assertEqual(after.source_revision, 1)
        self.assertGreater(after.scene_sequence, before.scene_sequence)

    def test_display_failure_does_not_mutate_training_or_section8_scene(self):
        failing_graphics = TactileGraphicsController(_FailingDisplay())
        failing_sync = TactileSyncController(failing_graphics)
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-display-failure",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )
        training_before = session.snapshot()

        with self.assertRaisesRegex(TactileSyncError, "tactile position refresh failed"):
            failing_sync.sync_training(session)

        self.assertEqual(session.snapshot(), training_before)
        self.assertIsNone(failing_graphics.current_scene)
        status = failing_sync.snapshot()
        self.assertEqual(status.state, TactileSyncState.ERROR)
        self.assertEqual(status.status_key, "tactile.status.refresh_failed")
        self.assertEqual(status.sync_revision, 0)

    def test_command_surface_fails_closed_on_wrong_context(self):
        with self.assertRaises(TactileSyncError):
            self.sync.dispatch("tactile.unknown")
        with self.assertRaises(TactileSyncError):
            self.sync.dispatch(TactileSyncCommand.STATUS, {})
        with self.assertRaises(TactileSyncError):
            self.sync.dispatch(TactileSyncCommand.REFRESH_PGN, Board().fen())
        with self.assertRaises(TactileSyncError):
            self.sync.dispatch(TactileSyncCommand.REFRESH_TRAINING, object())


if __name__ == "__main__":
    unittest.main()
