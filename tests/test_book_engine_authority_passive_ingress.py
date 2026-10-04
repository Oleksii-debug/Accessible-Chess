from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.bookdocument import BookDocument, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import EngineContractError, EngineContractErrorCode


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

    def test_exact_provider_chain_remains_canonical(self) -> None:
        analysis = AnalysisService(lambda: _IdleEngine())
        self.addCleanup(analysis.close)
        assisted = EngineAssistedWorkflowService(analysis)

        workflow = BookBoardWorkflow(self._reader(), assisted)

        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)


if __name__ == "__main__":
    unittest.main()
