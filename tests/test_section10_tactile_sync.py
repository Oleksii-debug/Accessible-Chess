from __future__ import annotations

import unittest

from acs.book_board_workflow import BookBoardMode, BookBoardView
from acs.bookreader import ReadingLocation
from acs.chesscore import Board
from acs.pgn_document import PgnDocumentSession
from acs.tactile_sync import (
    TactilePositionSink,
    TactileSyncCommand,
    TactileSyncController,
    TactileSyncError,
    TactileSyncSource,
    TactileSyncState,
)
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.version2_pgn_commands import Version2PgnCommands


class _RecordingSink:
    def __init__(self) -> None:
        self.frames: list[tuple[str, TactileSyncSource, int]] = []

    def present_position(
        self,
        canonical_fen: str,
        *,
        source: TactileSyncSource,
        revision: int,
    ) -> None:
        self.frames.append((canonical_fen, source, revision))


class _FailingSink:
    def present_position(
        self,
        canonical_fen: str,
        *,
        source: TactileSyncSource,
        revision: int,
    ) -> None:
        raise OSError("device/provider detail must not escape")


class TactileSyncContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sink = _RecordingSink()
        self.controller = TactileSyncController(self.sink)

    def test_sink_protocol_and_idle_status_are_accessible_semantic_state(self):
        self.assertIsInstance(self.sink, TactilePositionSink)
        snapshot = self.controller.dispatch(TactileSyncCommand.STATUS)
        self.assertEqual(snapshot.state, TactileSyncState.IDLE)
        self.assertEqual(snapshot.status_key, "tactile.status.idle")
        self.assertIsNone(snapshot.source)
        self.assertIsNone(snapshot.canonical_fen)

    def test_direct_canonical_position_refresh_never_creates_chess_truth(self):
        fen = Board().fen()
        snapshot = self.controller.sync_position(fen, source_revision=7)
        self.assertEqual(snapshot.canonical_fen, fen)
        self.assertEqual(snapshot.source, TactileSyncSource.POSITION)
        self.assertEqual(snapshot.source_revision, 7)
        self.assertEqual(self.sink.frames, [(fen, TactileSyncSource.POSITION, 1)])

        with self.assertRaises(TactileSyncError):
            self.controller.sync_position("  " + fen)
        self.assertEqual(len(self.sink.frames), 1)

    def test_pgn_gametree_cursor_refresh_uses_canonical_current_fen(self):
        session = PgnDocumentSession.from_text(
            '[Event "Section10"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
        )
        commands = Version2PgnCommands(lambda: session)

        start = self.controller.sync_pgn(commands)
        self.assertEqual(start.canonical_fen, commands.current_fen())

        session.workspace.next_move()
        after_e4 = self.controller.sync_pgn(commands)
        self.assertEqual(after_e4.canonical_fen, commands.current_fen())
        self.assertNotEqual(after_e4.canonical_fen, start.canonical_fen)

        session.workspace.next_move()
        after_e5 = self.controller.dispatch(
            TactileSyncCommand.REFRESH_PGN,
            commands,
        )
        self.assertEqual(after_e5.canonical_fen, commands.current_fen())
        self.assertEqual(after_e5.source, TactileSyncSource.PGN)
        self.assertEqual([item[2] for item in self.sink.frames], [1, 2, 3])

    def test_book_board_view_refresh_preserves_exact_return_origin(self):
        fen = Board().fen()
        origin = ReadingLocation(
            index=4,
            kind="Position",
            block_id="pos-4",
            source_anchor="chapter-2",
            heading_path=("Chapter 2",),
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
            revision=11,
        )

        snapshot = self.controller.sync_book_view(view)

        self.assertEqual(snapshot.source, TactileSyncSource.BOOK)
        self.assertEqual(snapshot.source_revision, 11)
        self.assertEqual(snapshot.canonical_fen, fen)
        self.assertEqual(view.origin, origin)
        self.assertEqual(view.origin.index, 4)
        self.assertEqual(view.origin.source_anchor, "chapter-2")

    def test_training_refresh_updates_after_accepted_answer(self):
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-training",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )

        before = self.controller.sync_training(session)
        self.assertEqual(before.canonical_fen, start)
        self.assertEqual(before.source_revision, 0)

        result = session.submit("e4")
        self.assertTrue(result.correct)

        after = self.controller.dispatch(
            TactileSyncCommand.REFRESH_TRAINING,
            session,
        )
        self.assertEqual(after.canonical_fen, session.current_fen)
        self.assertNotEqual(after.canonical_fen, before.canonical_fen)
        self.assertEqual(after.source_revision, 1)
        self.assertEqual(after.source, TactileSyncSource.TRAINING)

    def test_incorrect_training_answer_republishes_same_canonical_position(self):
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-training-wrong",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )
        first = self.controller.sync_training(session)
        result = session.submit("d4")
        self.assertFalse(result.correct)
        second = self.controller.sync_training(session)

        self.assertEqual(second.canonical_fen, first.canonical_fen)
        self.assertEqual(second.source_revision, 1)
        self.assertGreater(second.sync_revision, first.sync_revision)

    def test_sink_failure_does_not_mutate_canonical_training_state(self):
        failing = TactileSyncController(_FailingSink())
        start = Board().fen()
        session = ExerciseSession(
            ExerciseDefinition(
                exercise_id="section10-failure",
                start_fen=start,
                steps=(ExerciseStep(frozenset({"e4"})),),
            )
        )
        before = session.snapshot()

        with self.assertRaisesRegex(TactileSyncError, "tactile position refresh failed"):
            failing.sync_training(session)

        self.assertEqual(session.snapshot(), before)
        status = failing.snapshot()
        self.assertEqual(status.state, TactileSyncState.ERROR)
        self.assertEqual(status.status_key, "tactile.status.refresh_failed")
        self.assertEqual(status.canonical_fen, start)
        self.assertEqual(status.sync_revision, 0)

    def test_commands_fail_closed_on_wrong_source_types_and_unknown_ids(self):
        with self.assertRaises(TactileSyncError):
            self.controller.dispatch("tactile.unknown")
        with self.assertRaises(TactileSyncError):
            self.controller.dispatch(TactileSyncCommand.STATUS, {})
        with self.assertRaises(TactileSyncError):
            self.controller.dispatch(TactileSyncCommand.REFRESH_PGN, Board().fen())
        with self.assertRaises(TactileSyncError):
            self.controller.dispatch(TactileSyncCommand.REFRESH_TRAINING, object())


if __name__ == "__main__":
    unittest.main()
