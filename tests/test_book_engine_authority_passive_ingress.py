from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.bookdocument import BookDocument, Diagram, Exercise, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.full_product_actions import ActionDispatchResult
from acs.version2_windows_book_board_adapter import BookBoardUiEvent, BookBoardUiEventKind
from acs.version2_book_workspace import Version2BookWebViewProjection


class _IdleEngine:
    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        return ()

    def close(self) -> None:
        pass


class BookEngineAuthorityPassiveIngressTests(unittest.TestCase):
    @staticmethod
    def _reader() -> BookReader:
        return BookReader(
            BookDocument(
                "Engine authority",
                blocks=[Position(fen=Board.START, block_id="start")],
            )
        )

    def test_assisted_service_rejects_analysis_service_subclass(self) -> None:
        class HostileAnalysisService(AnalysisService):
            pass

        hostile = HostileAnalysisService.__new__(HostileAnalysisService)

        with self.assertRaises(EngineContractError) as caught:
            EngineAssistedWorkflowService(hostile)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_PROVIDER)

    def test_bookboard_rejects_assisted_service_subclass(self) -> None:
        class HostileAssistedService(EngineAssistedWorkflowService):
            pass

        hostile = HostileAssistedService.__new__(HostileAssistedService)

        with self.assertRaisesRegex(
            TypeError,
            "^engine_assistance must be EngineAssistedWorkflowService$",
        ):
            BookBoardWorkflow(self._reader(), hostile)

    def test_book_workspace_rejects_workflow_subclass_before_authority_hooks(self) -> None:
        class HostileBookBoardWorkflow(BookBoardWorkflow):
            touched = False

            def __getattribute__(self, name):
                if name in {"active", "revision", "semantic_game_snapshot"}:
                    type(self).touched = True
                    raise AssertionError("BookBoardWorkflow subclass hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileBookBoardWorkflow.__new__(HostileBookBoardWorkflow)

        with self.assertRaisesRegex(
            TypeError,
            "^V2 Books requires the canonical reader and workflow$",
        ):
            Version2BookWebViewProjection(
                self._reader(),
                hostile,
                lambda *_args: None,
            )

        self.assertFalse(HostileBookBoardWorkflow.touched)

    def test_book_workspace_rejects_active_action_result_before_value_probe(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        reader = self._reader()
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )

        class ActiveResult:
            touched = False

            def __getattribute__(self, name):
                if name == "value":
                    type(self).touched = True
                    raise AssertionError("active result value hook must not execute")
                return super().__getattribute__(name)

        projection = Version2BookWebViewProjection(
            reader,
            workflow,
            lambda *_args: ActiveResult(),
        )

        self.assertFalse(
            projection._workflow_action(
                "book.open_position",
                BookBoardUiEventKind.BOARD_OPENED,
            )
        )
        self.assertFalse(ActiveResult.touched)

    def test_book_workspace_rejects_active_ui_event_subclass_before_field_access(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        reader = self._reader()
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )

        class ActiveBookBoardUiEvent(BookBoardUiEvent):
            touched = False

            def __getattribute__(self, name):
                if name in {"kind", "action_id", "revision"}:
                    type(self).touched = True
                    raise AssertionError("active UI event field hook must not execute")
                return super().__getattribute__(name)

        active = ActiveBookBoardUiEvent.__new__(ActiveBookBoardUiEvent)
        projection = Version2BookWebViewProjection(
            reader,
            workflow,
            lambda *_args: active,
        )

        self.assertFalse(
            projection._workflow_action(
                "book.open_position",
                BookBoardUiEventKind.BOARD_OPENED,
            )
        )
        self.assertFalse(ActiveBookBoardUiEvent.touched)

    def test_book_workspace_rejects_active_wrapper_action_id_before_comparison(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        reader = self._reader()
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )

        class ActiveActionId(str):
            touched = False

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("active wrapper action comparison must not execute")

            def __ne__(self, other):
                type(self).touched = True
                raise AssertionError("active wrapper action comparison must not execute")

        event = BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.open_position",
            focus_target="board",
            revision=workflow.revision,
        )
        wrapped = ActionDispatchResult(
            action_id=ActiveActionId("book.open_position"),
            handled_by_shell=False,
            value=event,
        )
        projection = Version2BookWebViewProjection(
            reader,
            workflow,
            lambda *_args: wrapped,
        )

        self.assertFalse(
            projection._workflow_action(
                "book.open_position",
                BookBoardUiEventKind.BOARD_OPENED,
            )
        )
        self.assertFalse(ActiveActionId.touched)

    def test_book_workspace_rejects_mutated_active_event_scalar_before_comparison(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        reader = self._reader()
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )

        class ActiveActionId(str):
            touched = False

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("active event action comparison must not execute")

            def __ne__(self, other):
                type(self).touched = True
                raise AssertionError("active event action comparison must not execute")

        event = BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.open_position",
            focus_target="board",
            revision=workflow.revision,
        )
        object.__setattr__(event, "action_id", ActiveActionId("book.open_position"))
        projection = Version2BookWebViewProjection(
            reader,
            workflow,
            lambda *_args: event,
        )

        self.assertFalse(
            projection._workflow_action(
                "book.open_position",
                BookBoardUiEventKind.BOARD_OPENED,
            )
        )
        self.assertFalse(ActiveActionId.touched)

    def test_book_workspace_accepts_exact_router_result_with_exact_ui_event(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        reader = self._reader()
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )
        workflow.open_current()
        event = BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.open_position",
            focus_target="board",
            revision=workflow.revision,
        )
        wrapped = ActionDispatchResult(
            action_id="book.open_position",
            handled_by_shell=False,
            value=event,
        )
        projection = Version2BookWebViewProjection(
            reader,
            workflow,
            lambda *_args: wrapped,
        )

        self.assertTrue(
            projection._workflow_action(
                "book.open_position",
                BookBoardUiEventKind.BOARD_OPENED,
            )
        )

    def test_book_block_analysis_rejects_semantic_subclass_before_attribute_hooks(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        class HostilePosition(Position):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name == "fen":
                    type(self).touched = True
                    raise AssertionError("rejected Book semantic subclass must stay passive")
                return super().__getattribute__(name)

        hostile = HostilePosition(fen=Board.START)
        HostilePosition.armed = True

        with self.assertRaises(EngineContractError) as caught:
            assisted.analyze_book_block(hostile)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(HostilePosition.touched)

    def test_exact_book_block_roots_remain_supported_for_engine_analysis(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        exact_blocks = (
            Position(fen=Board.START),
            Diagram(fen=Board.START, alt_text="Start"),
            VariationTree(root_fen=Board.START, pgn="1. e4"),
            Exercise(fen=Board.START, prompt="Move", answer_text="e4"),
        )
        for block in exact_blocks:
            with self.subTest(kind=type(block).__name__):
                result = assisted.analyze_book_block(block)
                self.assertFalse(result.stale)
                self.assertEqual(result.fen, Board.START)

    def test_exact_provider_chain_remains_canonical(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        workflow = BookBoardWorkflow(self._reader(), assisted)

        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)


if __name__ == "__main__":
    unittest.main()
