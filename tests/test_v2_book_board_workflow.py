from __future__ import annotations

import threading
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

    def test_constructor_rejects_reader_subclass_before_reader_hooks(self) -> None:
        document = BookDocument(
            title="Passive workflow ingress",
            blocks=[Paragraph(text="Intro")],
        )

        class HostileReader(BookReader):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "location",
                    "block_snapshot",
                    "snapshot",
                    "navigation_availability",
                }:
                    type(self).touched = True
                    raise AssertionError("rejected BookReader subclass hook must not execute")
                return super().__getattribute__(name)

        reader = HostileReader(document)
        HostileReader.armed = True

        with self.assertRaisesRegex(TypeError, "^reader must be BookReader$"):
            self._workflow(reader)

        self.assertFalse(HostileReader.touched)

    def test_semantic_game_snapshot_is_detached_read_only_and_variation_complete(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[
                Game(
                    pgn=EMBEDDED_GAME,
                    title="Annotated game",
                    block_id="game",
                )
            ],
        )
        reader = BookReader(document)
        progress_before = reader.snapshot()
        workflow, _engine, _analysis = self._workflow(reader)

        mode, game, warnings = workflow.semantic_game_snapshot(0)

        self.assertEqual(mode, BookBoardMode.GAME)
        self.assertEqual(game.line.moves[0].san, "e4")
        self.assertEqual(game.line.moves[0].variations[0].moves[0].san, "d4")
        self.assertIn("Main", tuple(c.text for c in game.line.moves[0].comments_after))
        self.assertEqual(tuple(game.warnings), warnings)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

        game.tags["Event"] = "mutated detached copy"
        _, second, _ = workflow.semantic_game_snapshot(0)
        self.assertEqual(second.tags.get("Event"), "Book workflow")
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_semantic_game_snapshot_fails_closed_on_wrong_reader_location(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[
                Paragraph(text="Before"),
                Game(pgn=EMBEDDED_GAME, block_id="game"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(1)
        progress_before = reader.snapshot()
        workflow, _engine, _analysis = self._workflow(reader)

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.semantic_game_snapshot(0)

        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_semantic_game_snapshot_rejects_nonexact_or_unsupported_index(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Paragraph(text="No game here")],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)
        progress_before = reader.snapshot()

        for invalid in (True, -1, 0.0, "0"):
            with self.subTest(index=invalid):
                with self.assertRaises(BookBoardWorkflowError) as caught:
                    workflow.semantic_game_snapshot(invalid)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, BookBoardWorkflowCode.INVALID_COMMAND)

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.semantic_game_snapshot(0)
        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.UNSUPPORTED_BLOCK)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

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
            progress_during,
            progress_before,
            "read-only Book Board review must not publish transient origin state",
        )

        restored = workflow.return_to_book()
        self.assertEqual(restored, origin)
        self.assertEqual(reader.location(), origin)
        self.assertEqual(
            reader.snapshot(),
            progress_before,
            "returning from Book Board must preserve exact durable reader progress",
        )
        self.assertFalse(workflow.active)

    def test_corrupted_indexed_book_fen_fails_closed_before_progress_mutation(self) -> None:
        # PR #380 owns constructor-time Book FEN parity.  This application seam
        # still protects against a corrupted block snapshot crossing the reader
        # boundary, including None which canonical Board treats as START for its
        # own convenience API.  Live BookDocument mutation is revision drift and
        # is covered separately by the RETURN_FAILED race regressions below.
        for invalid_fen in (None, "", "8/8/8/8/8/8/8/8 w - - 0 1"):
            with self.subTest(invalid_fen=invalid_fen):
                position = Position(fen=Board.START, block_id="bad")
                document = BookDocument(title="Book", blocks=[position])
                reader = BookReader(document)
                corrupted = reader.block_snapshot(0)
                corrupted.fen = invalid_fen  # type: ignore[assignment]
                reader.block_snapshot = (  # type: ignore[method-assign]
                    lambda _index, block=corrupted: block
                )
                workflow, _engine, _analysis = self._workflow(reader)

                with self.assertRaises(BookBoardWorkflowError) as caught:
                    workflow.open_current()
                self.assertEqual(
                    caught.exception.code, BookBoardWorkflowCode.INVALID_POSITION
                )
                self.assertFalse(workflow.active)
                self.assertEqual(reader.location().index, 0)
                with self.assertRaises(LookupError):
                    reader.restore_return_point(workflow._RETURN_POINT)

    def test_open_current_sanitizes_reader_stale_before_origin_capture(self) -> None:
        position = Position(fen=Board.START, block_id="already-stale")
        document = BookDocument(title="Book", blocks=[position])
        reader = BookReader(document)
        workflow, engine, _analysis = self._workflow(reader)
        position.caption = "changed before Board open"

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.open_current()

        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertNotIn("BookDocument changed", str(caught.exception))
        self.assertEqual(engine.calls, [])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)

    def test_open_current_rejects_revision_race_before_mutated_block_is_consumed(self) -> None:
        position = Position(fen=Board.START, block_id="race-pos")
        document = BookDocument(title="Book", blocks=[position])
        reader = BookReader(document)
        workflow, engine, _analysis = self._workflow(reader)
        original_location = reader.location
        first_call = True
        changed = Board()
        changed.push_text("e4")
        changed_fen = changed.fen()

        def location_then_mutate():
            nonlocal first_call
            location = original_location()
            if first_call:
                first_call = False
                position.fen = changed_fen
            return location

        canonical_inputs: list[object] = []
        real_canonical = workflow._canonical_fen

        def guarded_canonical(value: object) -> str:
            canonical_inputs.append(value)
            return real_canonical(value)

        reader.location = location_then_mutate  # type: ignore[method-assign]
        workflow._canonical_fen = guarded_canonical  # type: ignore[method-assign]

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.open_current()

        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertEqual(
            canonical_inputs,
            [],
            "revision drift must fail before mutated chess/content is consumed",
        )
        self.assertEqual(engine.calls, [])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)

    def test_open_current_sanitizes_revision_drift_after_indexed_snapshot(self) -> None:
        position = Position(fen=Board.START, block_id="post-snapshot-race")
        document = BookDocument(title="Book", blocks=[position])
        reader = BookReader(document)
        workflow, engine, _analysis = self._workflow(reader)
        real_snapshot = reader.block_snapshot

        def snapshot_then_mutate(index: int):
            block = real_snapshot(index)
            position.caption = "changed after indexed snapshot"
            return block

        reader.block_snapshot = snapshot_then_mutate  # type: ignore[method-assign]

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.open_current()

        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertNotIn("BookDocument changed", str(caught.exception))
        self.assertEqual(engine.calls, [])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)

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

    def test_return_invalidates_old_analysis_before_new_session_can_publish(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Position(fen=Board.START, block_id="serialized-return")],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)
        workflow.open_current()

        invalidate_started = threading.Event()
        release_invalidate = threading.Event()
        return_errors: list[BaseException] = []
        real_invalidate = workflow._engine.invalidate

        def gated_invalidate() -> int:
            invalidate_started.set()
            if not release_invalidate.wait(5):
                raise RuntimeError("test did not release analysis invalidation")
            return real_invalidate()

        workflow._engine.invalidate = gated_invalidate  # type: ignore[method-assign]

        def return_old_session() -> None:
            try:
                workflow.return_to_book()
            except BaseException as exc:  # preserve worker failure for the main assertion
                return_errors.append(exc)

        worker = threading.Thread(target=return_old_session, daemon=True)
        worker.start()
        self.assertTrue(
            invalidate_started.wait(5),
            "return did not reach the old-context invalidation boundary",
        )

        # The invalidation callback deliberately pauses.  A non-blocking acquire
        # from this thread must fail: otherwise a newer Book Board session could
        # publish in this exact gap and then be invalidated by the older Return.
        acquired_during_invalidate = workflow._lock.acquire(blocking=False)
        if acquired_during_invalidate:
            workflow._lock.release()

        release_invalidate.set()
        worker.join(5)
        workflow._engine.invalidate = real_invalidate  # type: ignore[method-assign]

        self.assertFalse(worker.is_alive())
        self.assertEqual(return_errors, [])
        self.assertFalse(
            acquired_during_invalidate,
            "Book Board lock was released before old-context analysis invalidation",
        )
        self.assertFalse(workflow.active)

        # A successor context starts only after the old invalidation is complete;
        # its first analysis therefore remains current instead of being cancelled.
        workflow.open_current()
        successor = workflow.analyze(multipv=1, depth=8)
        self.assertFalse(successor.stale)
        self.assertIsNone(successor.error)

    def test_return_invalidation_failure_keeps_session_and_revision_recoverable(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Position(fen=Board.START, block_id="invalidate-failure")],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)
        workflow.open_current()
        before_revision = workflow.revision
        before_view = workflow.view()
        real_invalidate = workflow._engine.invalidate

        with patch.object(
            workflow._engine,
            "invalidate",
            side_effect=RuntimeError("analysis invalidation unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalidation unavailable"):
                workflow.return_to_book()

        self.assertTrue(workflow.active)
        self.assertEqual(workflow.revision, before_revision)
        self.assertEqual(workflow.view(), before_view)

        workflow._engine.invalidate = real_invalidate  # type: ignore[method-assign]
        restored = workflow.return_to_book()
        self.assertEqual(restored.index, reader.index)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, before_revision + 1)

    def test_return_invalidation_abort_keeps_session_and_revision_recoverable(self) -> None:
        class AbortSignal(BaseException):
            pass

        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Position(fen=Board.START, block_id="invalidate-abort")],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)
        workflow.open_current()
        before_revision = workflow.revision
        before_view = workflow.view()

        with patch.object(
            workflow._engine,
            "invalidate",
            side_effect=AbortSignal("analysis invalidation aborted"),
        ):
            with self.assertRaises(AbortSignal):
                workflow.return_to_book()

        self.assertTrue(workflow.active)
        self.assertEqual(workflow.revision, before_revision)
        self.assertEqual(workflow.view(), before_view)

        restored = workflow.return_to_book()
        self.assertEqual(restored.index, reader.index)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, before_revision + 1)

    def test_failed_return_keeps_session_recoverable(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="p1")],
        )
        reader = BookReader(document)
        workflow, _engine, _analysis = self._workflow(reader)
        workflow.open_current()
        document.blocks[0].caption = "changed after reader index"
        invalidation_calls = 0
        real_invalidate = workflow._engine.invalidate

        def counted_invalidate() -> int:
            nonlocal invalidation_calls
            invalidation_calls += 1
            return real_invalidate()

        workflow._engine.invalidate = counted_invalidate  # type: ignore[method-assign]
        try:
            with self.assertRaises(BookBoardWorkflowError) as caught:
                workflow.return_to_book()
        finally:
            workflow._engine.invalidate = real_invalidate  # type: ignore[method-assign]

        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertEqual(
            invalidation_calls,
            0,
            "failed Book return must keep the active analysis context valid",
        )
        self.assertTrue(workflow.active)
        self.assertEqual(workflow.board_snapshot().fen(), Board.START)

    def test_dispatch_rejects_payload_subclass_before_mapping_hooks(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Game(pgn='''[Result "*"]\n\n1. e4 *\n''')],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)

        class HostilePayload(dict):
            armed = False
            touched = False

            def _touch(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("rejected payload mapping hook must not execute")

            def __len__(self):
                self._touch()
                return super().__len__()

            def __iter__(self):
                self._touch()
                return super().__iter__()

            def __getitem__(self, key):
                self._touch()
                return super().__getitem__(key)

            def keys(self):
                self._touch()
                return super().keys()

        payload = HostilePayload({"depth": 8})
        HostilePayload.armed = True

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.dispatch(BookBoardCommand.ANALYZE, payload)
        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.INVALID_COMMAND)
        self.assertFalse(HostilePayload.touched)

    def test_dispatch_rejects_overwide_exact_payload_before_key_hooks(self) -> None:
        reader = BookReader(
            BookDocument(
                title="Book",
                blocks=[Game(pgn='''[Result "*"]\n\n1. e4 *\n''')],
            )
        )
        workflow, _engine, _analysis = self._workflow(reader)

        class HostileKey(str):
            armed = False
            touched = False

            def __hash__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-wide payload key must not be hashed")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("over-wide payload key must not be compared")
                return super().__eq__(other)

        hostile = HostileKey("extra")
        payload = {"multipv": 1, "depth": 8, hostile: 1}
        HostileKey.armed = True

        with self.assertRaises(BookBoardWorkflowError) as caught:
            workflow.dispatch(BookBoardCommand.ANALYZE, payload)
        self.assertEqual(caught.exception.code, BookBoardWorkflowCode.INVALID_COMMAND)
        self.assertFalse(HostileKey.touched)

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
