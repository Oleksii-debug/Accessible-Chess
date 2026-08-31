from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import (
    BookBoardCommand,
    BookBoardMode,
    BookBoardWorkflow,
    BookBoardWorkflowCode,
    BookBoardWorkflowError,
)
from acs.book_game_content import BookGameSource
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.bookdocument import BookDocument, Game, Paragraph, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import RawAnalysisLine
from acs.pgn_roundtrip import parse_pgn_text


EMBEDDED_GAME = '''[Event "Book workflow"]
[Result "*"]

1. e4 {Main} (1. d4 $1 d5) e5 2. Nf3 *
'''

LIBRARY_GAME = '''[Event "Library workflow"]
[Site "Kyiv"]
[Result "*"]

1. e4?! {Library comment} (1. d4 $1) e5 *
'''


class _FakeAnalysisEngine:
    def __init__(self, *, callback=None, failure: Exception | None = None) -> None:
        self.callback = callback
        self.failure = failure
        self.calls: list[tuple[str, int, int]] = []
        self.closed = False

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.calls.append((fen, multipv, depth))
        if self.callback is not None:
            self.callback()
        if self.failure is not None:
            raise self.failure
        return (
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=24,
                pv=("e2e4",),
            ),
        )

    def close(self) -> None:
        self.closed = True


class BookBoardWorkflowTests(unittest.TestCase):
    def _workflow(
        self,
        reader: BookReader,
        *,
        game_lookup=None,
        callback=None,
        failure: Exception | None = None,
    ) -> tuple[BookBoardWorkflow, _FakeAnalysisEngine, AnalysisService]:
        engine = _FakeAnalysisEngine(callback=callback, failure=failure)
        analysis = AnalysisService(lambda: engine)
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)
        return (
            BookBoardWorkflow(
                reader,
                assisted,
                game_lookup=game_lookup,
            ),
            engine,
            analysis,
        )

    def test_fen_position_opens_on_canonical_board_and_returns_exactly(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[
                Paragraph(text="Before", block_id="p-before"),
                Position(fen=Board.START, caption="Study", block_id="pos-1"),
                Paragraph(text="After", block_id="p-after"),
            ],
        )
        reader = BookReader(document)
        reader.save_return_point("user-bookmark")
        reader.go_to(1)
        origin = reader.location()
        progress_before = reader.snapshot()
        workflow, _engine, _analysis = self._workflow(reader)

        view = workflow.open_current()
        self.assertEqual(view.mode, BookBoardMode.POSITION)
        self.assertEqual(view.origin, origin)
        self.assertEqual(view.current_fen, Board(Board.START).fen())
        self.assertIsNone(view.cursor)
        self.assertEqual(workflow.board_snapshot().fen(), view.current_fen)
        self.assertEqual(reader.location(), origin)

        progress_during = reader.snapshot()
        self.assertEqual(
            progress_during["current_target"], progress_before["current_target"]
        )
        self.assertEqual(
            progress_during["return_points"]["user-bookmark"],
            progress_before["return_points"]["user-bookmark"],
        )

        restored = workflow.return_to_book()
        self.assertEqual(restored, origin)
        self.assertEqual(reader.location(), origin)
        self.assertFalse(workflow.active)

    def test_corrupted_book_fen_fails_closed_before_progress_mutation(self) -> None:
        # PR #380 owns constructor-time Book FEN parity.  This application seam
        # still protects against a corrupted/mutated block arriving after normal
        # construction, including None which canonical Board treats as START for
        # its own convenience API.
        for invalid_fen in (None, "", "8/8/8/8/8/8/8/8 w - - 0 1"):
            with self.subTest(invalid_fen=invalid_fen):
                position = Position(fen=Board.START, block_id="bad")
                document = BookDocument(title="Book", blocks=[position])
                reader = BookReader(document)
                progress_before = reader.snapshot()
                position.fen = invalid_fen  # simulate corruption after validation
                workflow, _engine, _analysis = self._workflow(reader)

                with self.assertRaises(BookBoardWorkflowError) as caught:
                    workflow.open_current()
                self.assertEqual(
                    caught.exception.code, BookBoardWorkflowCode.INVALID_POSITION
                )
                self.assertFalse(workflow.active)
                self.assertEqual(reader.snapshot(), progress_before)

    def test_embedded_game_uses_canonical_gametree_navigation_and_rav_return(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Game(pgn=EMBEDDED_GAME, block_id="game-embedded")],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)
        opened = workflow.open_current()

        self.assertEqual(opened.mode, BookBoardMode.GAME)
        self.assertEqual(opened.source, BookGameSource.EMBEDDED)
        self.assertEqual(opened.current_fen, Board.START)
        detached = workflow.game_snapshot()
        self.assertEqual(detached.line.moves[0].san, "e4")
        self.assertIn("$1", detached.line.moves[0].variations[0].moves[0].nags)

        expected = Board()
        expected.push_text("e4")
        after_e4 = expected.fen()
        main = workflow.next_move()
        self.assertEqual(main.current_fen, after_e4)
        self.assertEqual(main.cursor.next_move_index, 1)

        branch_start = workflow.enter_variation(0)
        self.assertEqual(branch_start.current_fen, Board.START)
        self.assertEqual(branch_start.cursor.next_move_index, 0)
        expected_branch = Board()
        expected_branch.push_text("d4")
        self.assertEqual(workflow.next_move().current_fen, expected_branch.fen())

        resumed = workflow.leave_variation()
        self.assertEqual(resumed.current_fen, after_e4)
        self.assertEqual(resumed.cursor.next_move_index, 1)
        self.assertEqual(workflow.previous_move().current_fen, Board.START)

        # A caller can inspect a detached tree but cannot mutate the workflow tree.
        detached.line.moves[0].san = "mutated"
        self.assertEqual(workflow.game_snapshot().line.moves[0].san, "e4")

    def test_variationtree_root_fen_is_bound_only_for_canonical_legality_projection(self) -> None:
        root_board = Board()
        root_board.push_text("e4")
        root_fen = root_board.fen()
        variation = VariationTree(
            root_fen=root_fen,
            pgn='''[Event "Variation"]\n[Result "*"]\n\n1... c5 (1... e5) 2. Nf3 *\n''',
            block_id="var-1",
        )
        document = BookDocument(title="Book", blocks=[variation])
        reader = BookReader(document)
        workflow, _engine, _analysis = self._workflow(reader)
        source_before = variation.as_dict()

        opened = workflow.open_current()
        self.assertEqual(opened.mode, BookBoardMode.VARIATION)
        self.assertEqual(opened.current_fen, root_fen)
        self.assertEqual(variation.as_dict(), source_before)

        expected_main = Board(root_fen)
        expected_main.push_text("c5")
        main = workflow.next_move()
        self.assertEqual(main.current_fen, expected_main.fen())

        branch = workflow.enter_variation(0)
        self.assertEqual(branch.current_fen, root_fen)
        expected_branch = Board(root_fen)
        expected_branch.push_text("e5")
        self.assertEqual(workflow.next_move().current_fen, expected_branch.fen())
        self.assertEqual(workflow.leave_variation().current_fen, expected_main.fen())
        self.assertEqual(variation.as_dict(), source_before)

    def test_referenced_library_game_stays_read_only_and_detached(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("book-library.pgn", "pgn", "a" * 64)
            stored = parse_pgn_text(LIBRARY_GAME, strict=False)[0]
            stored.source_index = 37
            game_id = database.store_game(stored, source_id, raw_pgn=LIBRARY_GAME)
            lookup = AcsdbBookGameLookup(database)
            reader = BookReader(
                BookDocument(
                    title="Book",
                    blocks=[Game(game_id=game_id, block_id="game-ref")],
                )
            )
            workflow, _engine, _analysis = self._workflow(
                reader, game_lookup=lookup
            )
            changes_before = database.conn.total_changes

            opened = workflow.open_current()
            self.assertEqual(opened.source, BookGameSource.REFERENCE)
            self.assertEqual(opened.game_id, game_id)
            self.assertEqual(database.conn.total_changes, changes_before)
            first = workflow.game_snapshot()
            self.assertEqual(first.source_index, 37)
            self.assertEqual(first.line.moves[0].san, "e4")
            self.assertIn("?!", first.line.moves[0].nags)

            first.line.moves[0].san = "mutated"
            self.assertEqual(workflow.game_snapshot().line.moves[0].san, "e4")
            workflow.next_move()
            self.assertEqual(database.conn.total_changes, changes_before)
            self.assertEqual(lookup.load_book_game(game_id).line.moves[0].san, "e4")
            workflow.return_to_book()
            self.assertEqual(database.conn.total_changes, changes_before)

    def test_analysis_uses_existing_assisted_service_without_mutating_book_or_board(self) -> None:
        position = Position(fen=Board.START, block_id="analysis-pos")
        reader = BookReader(BookDocument(title="Book", blocks=[position]))
        workflow, engine, _analysis = self._workflow(reader)
        opened = workflow.open_current()
        origin = reader.location()
        block_before = position.as_dict()

        result = workflow.analyze(multipv=1, depth=12)

        self.assertFalse(result.stale)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.teacher_lines), 1)
        self.assertEqual(result.student_lines, ())
        self.assertEqual(engine.calls, [(opened.current_fen, 1, 12)])
        self.assertEqual(workflow.view(), opened)
        self.assertEqual(workflow.board_snapshot().fen(), opened.current_fen)
        self.assertEqual(reader.location(), origin)
        self.assertEqual(position.as_dict(), block_before)

    def test_engine_provider_details_are_sanitized_at_existing_assisted_boundary(self) -> None:
        reader = BookReader(
            BookDocument(title="Book", blocks=[Position(fen=Board.START)])
        )
        workflow, _engine, _analysis = self._workflow(
            reader,
            failure=RuntimeError(r"C:\private\stockfish.exe provider exploded"),
        )
        workflow.open_current()

        result = workflow.analyze(multipv=1, depth=8)

        self.assertFalse(result.stale)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.error, "engine analysis unavailable")
        self.assertNotIn("stockfish", result.error.lower())
        self.assertNotIn("\\", result.error)

    def test_navigation_during_analysis_forces_stale_application_result(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Game(pgn='''[Result "*"]\n\n1. e4 e5 *\n''')],
            )
        )
        holder: dict[str, BookBoardWorkflow] = {}

        def move_during_engine_request() -> None:
            holder["workflow"].next_move()

        workflow, _engine, _analysis = self._workflow(
            reader, callback=move_during_engine_request
        )
        holder["workflow"] = workflow
        workflow.open_current()

        result = workflow.analyze(multipv=1, depth=10)

        self.assertTrue(result.stale)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())
        self.assertIsNone(result.error)
        self.assertEqual(workflow.view().cursor.next_move_index, 1)

    def test_failed_return_keeps_session_recoverable(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="p1")],
        )
        reader = BookReader(document)
        workflow, _engine, _analysis = self._workflow(reader)
        workflow.open_current()
        document.blocks[0].caption = "changed after reader index"

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.return_to_book()
        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertTrue(workflow.active)
        self.assertEqual(workflow.board_snapshot().fen(), Board.START)

    def test_application_dispatch_is_closed_world_and_does_not_guess_payloads(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Game(pgn='''[Result "*"]\n\n1. e4 *\n''')],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)

        opened = workflow.dispatch(BookBoardCommand.OPEN_CURRENT)
        self.assertEqual(opened.mode, BookBoardMode.GAME)
        with self.assertRaises(BookBoardWorkflowError) as unknown:
            workflow.dispatch(BookBoardCommand.NEXT_MOVE, {"unexpected": 1})
        self.assertEqual(unknown.exception.code, BookBoardWorkflowCode.INVALID_COMMAND)
        self.assertEqual(workflow.view().cursor.next_move_index, 0)

        moved = workflow.dispatch("book_board.next_move")
        self.assertEqual(moved.cursor.next_move_index, 1)
        with self.assertRaises(BookBoardWorkflowError) as coercive:
            workflow.dispatch(BookBoardCommand.ANALYZE, {"depth": True})
        self.assertEqual(coercive.exception.code, BookBoardWorkflowCode.INVALID_COMMAND)
        restored = workflow.dispatch(BookBoardCommand.RETURN_TO_BOOK)
        self.assertEqual(restored, reader.location())


if __name__ == "__main__":
    unittest.main()
